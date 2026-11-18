"""Analisi "tengo o vendo" di una carta per l'app: raccoglie prezzi, storico e andamento del set, poi stima."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from cardbot.analysis.engine import MarketInputs, analyze
from cardbot.catalog.base import Catalog
from cardbot.collections.service import today
from cardbot.db import PriceHistory, ProductInfo, SetStats
from cardbot.prices.service import PriceService

REPRINT_WINDOW = timedelta(days=120)
REPRINT_GAP = timedelta(days=45)
DISCLAIMER = ("Stima statistica su dati pubblici di Cardmarket, non una previsione né un consiglio finanziario: "
              "il mercato delle carte può cambiare all'improvviso (ristampe, tornei, annunci).")


def _parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _history(session: Session, pid: int, price: float) -> list[tuple[date, float]]:
    """Storico giornaliero del prodotto; tra campi base e "-holo" quello che corrisponde al prezzo attuale."""
    best: list[tuple[date, float]] = []
    for fields in ("base", "holo"):
        rows = (session.query(PriceHistory).filter_by(id_product=pid, fields=fields)
                .order_by(PriceHistory.day).all())
        points = [(r.day, r.trend) for r in rows if r.trend]
        if points and (not best or abs(points[-1][1] - price) < abs(best[-1][1] - price)):
            best = points
    return best


async def card_analysis(session: Session, catalog: Catalog, prices: PriceService, lang: str, card_id: str,
                        variant: str) -> dict[str, Any]:
    primary = ["ja"] if lang in ("ja", "zh-tw") else ["it"]
    quotes = await prices.quotes(card_id, lang, variant, primary, with_graded=False)
    q = next((x for x in quotes if x.cardmarket and x.cardmarket.has_data), None)
    if q is None:
        return {"available": False, "reason": "Questa carta non ha prezzi su Cardmarket: impossibile analizzarla."}
    cm = q.cardmarket
    price = next((v for v in (cm.trend, cm.avg7, cm.avg30, cm.avg) if v), None)
    if not price:
        return {"available": False, "reason": "Prezzo di mercato non disponibile per questa carta."}

    card = await catalog.get_card(q.catalog_lang or lang, q.card_id or card_id) or {}
    set_brief = card.get("set") or {}
    set_detail = await catalog.get_set(q.catalog_lang or lang, set_brief.get("id", "")) or {}

    pid = int(cm.id_product) if cm.id_product else None
    history = _history(session, pid, price) if pid else []
    info = session.get(ProductInfo, pid) if pid else None
    set_rows: list[SetStats] = []
    reprinted, prints, reprint_date = False, 0, None
    release = _parse_day(set_detail.get("releaseDate"))
    if info is not None:
        if info.id_expansion is not None:
            set_rows = (session.query(SetStats).filter_by(id_expansion=info.id_expansion)
                        .order_by(SetStats.day).all())
            if release is None:
                first = (session.query(ProductInfo.date_added).filter(ProductInfo.id_expansion == info.id_expansion,
                                                                      ProductInfo.date_added.isnot(None))
                         .order_by(ProductInfo.date_added).first())
                release = first[0] if first else None
        if info.id_metacard is not None:
            siblings = session.query(ProductInfo).filter_by(id_metacard=info.id_metacard).all()
            prints = len(siblings)
            # Ristampa: stessa carta in un'altra espansione, uscita almeno 45 giorni dopo questa e negli ultimi 4 mesi
            # (le versioni uscite insieme, es. promo dello stesso periodo, non contano).
            later = [s.date_added for s in siblings
                     if s.id_product != pid and s.id_expansion != info.id_expansion and s.date_added
                     and s.date_added >= today() - REPRINT_WINDOW
                     and (info.date_added is None or s.date_added >= info.date_added + REPRINT_GAP)]
            reprinted, reprint_date = bool(later), max(later) if later else None
    latest_set = set_rows[-1] if set_rows else None

    result = analyze(MarketInputs(
        price=price, low=cm.low, avg1=cm.avg1, avg7=cm.avg7, avg30=cm.avg30, history=history,
        set_change_7d=latest_set.median_change_7d if latest_set else None,
        set_change_30d=latest_set.median_change_30d if latest_set else None,
        set_share_up=latest_set.share_up_30d if latest_set else None,
        set_index=[(r.day, r.total_trend) for r in set_rows], release_date=release, rarity=card.get("rarity"),
        reprinted_recently=reprinted, reprint_date=reprint_date, other_prints=prints, today=today(),
    ))
    return {
        "available": True, "price": price, "currency": cm.currency, "updated": cm.updated.isoformat() if cm.updated else None,
        "priced_card": q.card_label, "priced_langs": q.langs, "estimated_equivalent": q.estimated_equivalent,
        "verdict": result.verdict, "verdict_label": result.verdict_label, "summary": result.summary,
        "p_down": result.p_down, "p_up": round(1 - result.p_down, 2), "expected_change": result.expected_change,
        "range_low": result.range_low, "range_high": result.range_high, "horizon_days": 30,
        "confidence": result.confidence, "net_if_sold": result.net_if_sold, "notes": result.notes,
        "signals": [{"key": s.key, "title": s.title, "detail": s.detail, "score": round(s.score, 2),
                     "direction": s.direction} for s in result.signals],
        "history": [{"day": d.isoformat(), "price": v} for d, v in history[-120:]],
        "averages": [{"label": label, "value": v} for label, v in (("Media 30 gg", cm.avg30), ("Media 7 gg", cm.avg7),
                                                                     ("Ieri", cm.avg1), ("Oggi", price)) if v],
        "set": None if latest_set is None else {
            "name": set_detail.get("name") or set_brief.get("name"), "cards": latest_set.cards,
            "change_7d": latest_set.median_change_7d, "change_30d": latest_set.median_change_30d,
            "share_up": latest_set.share_up_30d,
            "index": [{"day": r.day.isoformat(), "value": r.total_trend} for r in set_rows[-120:]],
        },
        "release_date": release.isoformat() if release else None,
        "disclaimer": DISCLAIMER,
    }
