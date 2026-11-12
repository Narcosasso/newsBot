"""Creazione e aggiornamento dei tracking (carta + variante + lingue) e dei relativi prezzi sorvegliati."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from cardbot.alerts.rules import metric
from cardbot.db import Tracking, TrackingTarget, User, utcnow
from cardbot.prices.models import LangQuote


def target_specs(quotes: list[LangQuote]) -> list[dict[str, Any]]:
    """Dalle quotazioni mostrate all'utente, i prezzi tracciabili (serializzabili nello stato della chat)."""
    specs = []
    for q in quotes:
        cm = q.cardmarket
        if not (q.card_id and cm and cm.id_product and metric(cm) is not None):
            continue
        specs.append({
            "langs": q.langs, "card_id": q.card_id, "catalog_lang": q.catalog_lang or "en",
            "id_product": int(cm.id_product), "shared_product": q.shared_product, "aggregated": q.aggregated,
            "baseline": metric(cm),
        })
    return specs


@dataclass
class TrackingResult:
    tracking: Tracking
    created: bool
    tracked_langs: list[str] = field(default_factory=list)
    untracked_langs: list[str] = field(default_factory=list)


def upsert_tracking(session: Session, user: User, *, card_id: str, catalog_lang: str, variant: str, label: str,
                    langs: list[str], specs: list[dict[str, Any]]) -> TrackingResult:
    tracking = (session.query(Tracking)
                .filter_by(user_id=user.id, card_id=card_id, catalog_lang=catalog_lang, variant=variant, active=True)
                .one_or_none())
    created = tracking is None
    if created:
        tracking = Tracking(user_id=user.id, card_id=card_id, catalog_lang=catalog_lang, variant=variant,
                            label=label, langs=",".join(langs))
        session.add(tracking)
        session.flush()
    else:
        tracking.langs = ",".join(langs)

    existing = {(t.id_product, t.langs): t for t in tracking.targets}
    keep = set()
    now = utcnow()
    for spec in specs:
        key = (spec["id_product"], ",".join(spec["langs"]))
        keep.add(key)
        target = existing.get(key)
        if target is not None and target.active:
            continue  # già sorvegliato: mantiene il proprio valore di riferimento
        if target is not None:  # riattivato: riparte dal prezzo mostrato ora
            target.active, target.baseline, target.baseline_at = True, spec["baseline"], now
            continue
        tracking.targets.append(TrackingTarget(
            langs=key[1], card_id=spec["card_id"], catalog_lang=spec["catalog_lang"], id_product=spec["id_product"],
            variant=variant, shared_product=spec["shared_product"], aggregated=spec["aggregated"],
            baseline=spec["baseline"], baseline_at=now,
        ))
    # I target non più richiesti si disattivano (non si cancellano: le notifiche passate li referenziano).
    for key, target in existing.items():
        if key not in keep:
            target.active = False

    tracked = [lang for s in specs for lang in s["langs"]]
    return TrackingResult(tracking=tracking, created=created, tracked_langs=tracked,
                          untracked_langs=[lang for lang in langs if lang not in tracked])
