"""Dati di mercato calcolati dal job notturno: prodotti Cardmarket e andamento di ogni espansione.

Fonti, entrambe pubbliche e offerte da Cardmarket, una richiesta al giorno ciascuna (con ETag):
- elenco prodotti (products_singles_6.json): per ogni carta l'espansione, la "metacarta" (la stessa carta in
  altre stampe) e la data in cui è stata aggiunta (≈ uscita);
- price guide (già scaricato per gli avvisi): prezzi di tutte le carte.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import date, datetime
from typing import Any

import httpx
from sqlalchemy import insert
from sqlalchemy.orm import Session

from cardbot.db import JobState, ProductInfo, SetStats

log = logging.getLogger(__name__)

PRODUCT_LIST_URL = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_6.json"
STATE_KEY = "product_list"
MIN_PRICE = 0.5  # sotto 50 centesimi i prezzi sono rumore (carte comuni): fuori dall'andamento del set


class CardmarketProductList:
    def __init__(self, url: str = PRODUCT_LIST_URL, client: httpx.AsyncClient | None = None) -> None:
        self._url = url
        self._http = client or httpx.AsyncClient(timeout=120.0, headers={"User-Agent": "cardbot/0.1"})

    async def fetch(self, etag: str | None = None) -> tuple[list[dict[str, Any]], str | None] | None:
        """(prodotti, etag) oppure None se il file non è cambiato."""
        resp = await self._http.get(self._url, headers={"If-None-Match": etag} if etag else {})
        if resp.status_code == 304:
            return None
        resp.raise_for_status()
        return resp.json().get("products") or [], resp.headers.get("etag")


def _day(value: str | None) -> date | None:
    if not value or value.startswith("0000"):
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def update_products(session: Session, products: list[dict[str, Any]]) -> int:
    """Aggiunge i prodotti nuovi (quelli già noti non cambiano). Restituisce quanti ne ha aggiunti."""
    known = {pid for (pid,) in session.query(ProductInfo.id_product).all()}
    new, seen = [], set()
    for p in products:
        pid = int(p.get("idProduct") or 0)
        if pid and pid not in known and pid not in seen:
            seen.add(pid)
            new.append({"id_product": pid, "id_expansion": p.get("idExpansion"), "id_metacard": p.get("idMetacard"),
                        "date_added": _day(p.get("dateAdded")), "name": (p.get("name") or "")[:200]})
    for i in range(0, len(new), 5000):  # la prima volta sono ~75.000 righe: inserimento a blocchi
        session.execute(insert(ProductInfo), new[i:i + 5000])
    return len(new)


async def refresh_products(session: Session, source: CardmarketProductList | None = None, force: bool = False) -> int:
    source = source or CardmarketProductList()
    state = session.get(JobState, STATE_KEY) or JobState(key=STATE_KEY, value={})
    try:
        got = await source.fetch(None if force else (state.value or {}).get("etag"))
    except Exception as exc:
        log.warning("Elenco prodotti Cardmarket non disponibile: %s", exc)
        return 0
    if got is None:
        return 0
    products, etag = got
    added = update_products(session, products)
    state.value = {"etag": etag}
    session.merge(state)
    return added


def _price(e: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """(trend, avg7, avg30) della riga: campi base, oppure "-holo" per le carte che esistono solo holo."""
    for sfx in ("", "-holo"):
        trend = e.get(f"trend{sfx}")
        if trend:
            return float(trend), e.get(f"avg7{sfx}") or None, e.get(f"avg30{sfx}") or None
    return None, None, None


def compute_set_stats(session: Session, entries: dict[int, dict[str, Any]], day: date) -> int:
    """Una riga per espansione e giorno: indice del set, variazione mediana a 7 e 30 giorni, quota in salita."""
    expansion_of = dict(session.query(ProductInfo.id_product, ProductInfo.id_expansion).all())
    groups: dict[int, list[tuple[float, float | None, float | None]]] = defaultdict(list)
    for pid, e in entries.items():
        exp = expansion_of.get(pid)
        trend, avg7, avg30 = _price(e)
        if exp is None or trend is None or trend < MIN_PRICE:
            continue
        groups[exp].append((trend, avg7, avg30))
    existing = {r.id_expansion: r for r in session.query(SetStats).filter_by(day=day).all()}
    for exp, rows in groups.items():
        ch7 = [t / a7 - 1 for t, a7, _ in rows if a7]
        ch30 = [t / a30 - 1 for t, _, a30 in rows if a30]
        row = existing.get(exp) or SetStats(id_expansion=exp, day=day, cards=0, total_trend=0)
        row.cards, row.total_trend = len(rows), round(sum(t for t, _, _ in rows), 2)
        row.median_change_7d = round(statistics.median(ch7), 4) if ch7 else None
        row.median_change_30d = round(statistics.median(ch30), 4) if ch30 else None
        row.share_up_30d = round(sum(1 for c in ch30 if c > 0.02) / len(ch30), 3) if ch30 else None
        if exp not in existing:
            session.add(row)
    session.flush()
    return len(groups)
