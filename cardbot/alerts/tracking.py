"""Creazione e aggiornamento dei tracking (carta + variante + lingue) e dei relativi prezzi sorvegliati."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from cardbot.alerts.rules import metric
from cardbot.db import Tracking, TrackingTarget, User, utcnow
from cardbot.langs import flag
from cardbot.prices.models import LangQuote

CARDMARKET = "cardmarket"
PSA10 = "psa10"


def target_tag(target) -> str:
    """Come si presenta un prezzo sorvegliato: bandiere delle lingue oppure '🏅 PSA 10'."""
    if target.source == PSA10:
        return "🏅 PSA 10"
    return "".join(flag(x) for x in target.langs.split(","))


def target_specs(quotes: list[LangQuote]) -> list[dict[str, Any]]:
    """Prezzi Cardmarket tracciabili fra quelli mostrati all'utente (serializzabili nello stato della chat)."""
    specs = []
    for q in quotes:
        cm = q.cardmarket
        if not (q.card_id and cm and cm.id_product and metric(cm) is not None):
            continue
        specs.append({
            "source": CARDMARKET, "langs": q.langs, "card_id": q.card_id, "catalog_lang": q.catalog_lang or "en",
            "id_product": int(cm.id_product), "external_id": None, "currency": cm.currency or "EUR",
            "shared_product": q.shared_product, "aggregated": q.aggregated, "baseline": metric(cm),
        })
    return specs


def graded_specs(quotes: list[LangQuote]) -> list[dict[str, Any]]:
    """Prezzi PSA 10 tracciabili (solo se ci sono vendite: senza un prezzo non c'è un riferimento)."""
    specs = []
    for q in quotes:
        g = q.graded
        if q.card_id and g is not None and g.has_sales:
            specs.append(graded_spec(q.langs, q.card_id, q.catalog_lang or "en", g))
    return specs


def graded_spec(langs: list[str], card_id: str, catalog_lang: str, g) -> dict[str, Any]:
    """La PSA 10 riguarda una sola stampa: inglese per le lingue internazionali, giapponese per le giapponesi."""
    return {
        "source": PSA10, "langs": ["ja"] if g.language == "japanese" else ["en"], "card_id": card_id, "catalog_lang": catalog_lang, "id_product": None,
        "external_id": g.tcgplayer_id, "currency": g.currency, "shared_product": True, "aggregated": False,
        "baseline": g.price,
    }


def _key(source: str, id_product: int | None, external_id: str | None, langs: str) -> tuple:
    return (source, id_product, external_id, langs)


@dataclass
class TrackingResult:
    tracking: Tracking
    created: bool
    tracked_langs: list[str] = field(default_factory=list)
    untracked_langs: list[str] = field(default_factory=list)
    graded: bool = False  # c'è (anche) un prezzo PSA 10 sorvegliato


def upsert_tracking(session: Session, user: User, *, card_id: str, catalog_lang: str, variant: str, label: str,
                    langs: list[str], specs: list[dict[str, Any]],
                    manage: frozenset[str] = frozenset({CARDMARKET})) -> TrackingResult:
    """Crea o aggiorna il tracking. Tocca solo i prezzi delle fonti in `manage`: cambiare le lingue non toglie
    la PSA 10, e aggiungere la PSA 10 non tocca i prezzi Cardmarket."""
    tracking = (session.query(Tracking)
                .filter_by(user_id=user.id, card_id=card_id, catalog_lang=catalog_lang, variant=variant, active=True)
                .one_or_none())
    created = tracking is None
    if created:
        tracking = Tracking(user_id=user.id, card_id=card_id, catalog_lang=catalog_lang, variant=variant,
                            label=label, langs=",".join(langs))
        session.add(tracking)
        session.flush()
    elif CARDMARKET in manage:
        tracking.langs = ",".join(langs)

    existing = {_key(t.source or CARDMARKET, t.id_product, t.external_id, t.langs): t for t in tracking.targets}
    keep = set()
    now = utcnow()
    for spec in specs:
        if spec["source"] not in manage:
            continue
        key = _key(spec["source"], spec["id_product"], spec["external_id"], ",".join(spec["langs"]))
        keep.add(key)
        target = existing.get(key)
        if target is not None and target.active:
            continue  # già sorvegliato: mantiene il proprio valore di riferimento
        if target is not None:  # riattivato: riparte dal prezzo mostrato ora
            target.active, target.baseline, target.baseline_at = True, spec["baseline"], now
            continue
        tracking.targets.append(TrackingTarget(
            source=spec["source"], langs=key[3], card_id=spec["card_id"], catalog_lang=spec["catalog_lang"],
            id_product=spec["id_product"], external_id=spec["external_id"], currency=spec["currency"],
            variant=variant, shared_product=spec["shared_product"], aggregated=spec["aggregated"],
            baseline=spec["baseline"], baseline_at=now, active=True,
        ))
    # I target non più richiesti si disattivano (non si cancellano: le notifiche passate li referenziano).
    for key, target in existing.items():
        if key[0] in manage and key not in keep:
            target.active = False

    active = [t for t in tracking.targets if t.active]
    tracked = [lang for t in active if (t.source or CARDMARKET) == CARDMARKET for lang in t.langs.split(",")]
    return TrackingResult(tracking=tracking, created=created, tracked_langs=tracked,
                          untracked_langs=[lang for lang in langs if lang not in tracked] if CARDMARKET in manage
                          else [], graded=any(t.source == PSA10 for t in active))
