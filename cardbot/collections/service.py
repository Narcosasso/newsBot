"""Collezioni: salvataggio delle carte, prezzo di ogni carta, valore totale e storico giornaliero.

Il prezzo di una carta posseduta è il "prezzo di mercato" Cardmarket (trend; se manca, media 7 o 30 giorni) della
sua variante. Si legge da TCGdex quando la carta entra in collezione e poi ogni notte dal price guide di Cardmarket
(un solo file per tutte le carte), che alimenta anche lo storico usato dai grafici e dall'analisi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from cardbot.catalog.base import Catalog
from cardbot.collections.importer import ImportPlan
from cardbot.db import Collection, CollectionItem, CollectionValue, PriceHistory, User, utcnow
from cardbot.prices.models import CM_FIELDS, cardmarket_quote, parse_datetime
from cardbot.prices.service import _shared_product
from cardbot.variants import variant_entry, variants_of

log = logging.getLogger(__name__)
ROME = ZoneInfo("Europe/Rome")


def today() -> date:
    return datetime.now(ROME).date()


def market_price(pricing: dict[str, Any] | None, variant: str, shared: bool) -> float | None:
    cm = cardmarket_quote(pricing, variant, shared)
    if cm is None:
        return None
    for value in (cm.trend, cm.avg7, cm.avg30, cm.avg):
        if value:
            return round(value, 2)
    return None


# --- salvataggio ---------------------------------------------------------------------------------------------

@dataclass
class ImportReport:
    collection_id: int
    collection_name: str
    imported: int = 0          # righe (carta+variante+lingua) salvate
    cards: int = 0             # copie totali
    review: list[dict[str, Any]] = field(default_factory=list)
    unmatched: list[dict[str, Any]] = field(default_factory=list)
    item_ids: list[int] = field(default_factory=list)


def get_or_create_collection(session: Session, user: User, name: str) -> Collection:
    found = session.query(Collection).filter_by(user_id=user.id, name=name).one_or_none()
    if found:
        return found
    c = Collection(user_id=user.id, name=name)
    session.add(c)
    session.flush()
    return c


def upsert_item(session: Session, collection: Collection, *, card_id: str, catalog_lang: str, variant: str,
                lang: str, quantity: int, name: str, set_id: str | None = None, set_name: str | None = None,
                variant_label: str | None = None, needs_review: bool = False, source: str = "app",
                add: bool = False, image: str | None = None) -> CollectionItem:
    """Crea o aggiorna la riga (stessa carta, variante e lingua). add=True somma la quantità invece di sostituirla."""
    item = (session.query(CollectionItem)
            .filter_by(collection_id=collection.id, catalog_lang=catalog_lang, card_id=card_id, variant=variant,
                       lang=lang).one_or_none())
    if item is None:
        item = CollectionItem(collection_id=collection.id, card_id=card_id, catalog_lang=catalog_lang,
                              variant=variant, lang=lang, quantity=0, name=name, set_id=set_id, set_name=set_name,
                              shared_product=True, needs_review=needs_review, source=source)
        session.add(item)
    item.quantity = (item.quantity or 0) + quantity if add else quantity
    item.variant_label = variant_label or item.variant_label
    item.image = item.image or image
    item.needs_review = needs_review or bool(item.needs_review and source != "app")
    session.flush()
    return item


def apply_plan(session: Session, user: User, plan: ImportPlan, collection_name: str | None = None) -> ImportReport:
    """Salva le carte abbinate. Reimportare lo stesso file aggiorna le quantità, non crea doppioni."""
    collection = get_or_create_collection(session, user, (collection_name or plan.collection_name)[:100])
    report = ImportReport(collection_id=collection.id, collection_name=collection.name)
    merged: dict[tuple[str, str, str, str], int] = {}
    for m in plan.matched:  # due righe del file sulla stessa carta e variante: si sommano
        key = (m.catalog_lang, m.card_id, m.variant, m.row.lang)
        merged[key] = merged.get(key, 0) + m.row.quantity
    done: set[tuple[str, str, str, str]] = set()
    for m in plan.matched:
        key = (m.catalog_lang, m.card_id, m.variant, m.row.lang)
        if key in done:
            continue
        done.add(key)
        label = None if m.row.variant_name.strip().lower() in ("normal", "holo", "reverse holo") else m.row.variant_name
        item = upsert_item(session, collection, card_id=m.card_id, catalog_lang=m.catalog_lang, variant=m.variant,
                           lang=m.row.lang, quantity=merged[key], name=m.name, set_id=m.set_id,
                           set_name=m.set_name, variant_label=label, needs_review=m.needs_review, source="import",
                           image=m.row.image)
        report.imported += 1
        report.cards += merged[key]
        report.item_ids.append(item.id)
        if m.needs_review:
            report.review.append({"item_id": item.id, "file": f"{m.row.name} {m.row.set_name} {m.row.number}",
                                  "matched": f"{m.name} · {m.set_name}", "card_id": m.card_id,
                                  "catalog_lang": m.catalog_lang})
    for row, reason in plan.unmatched:
        report.unmatched.append({"name": row.name, "set": row.set_name or row.set_code, "number": row.number,
                                 "quantity": row.quantity, "reason": reason})
    session.commit()
    return report


# --- dati e prezzi dal catalogo ------------------------------------------------------------------------------

async def refresh_items(sessions: sessionmaker[Session], catalog: Catalog, item_ids: list[int]) -> int:
    """Completa le carte con immagine, rarità e prezzo attuale (una richiesta al catalogo per carta, in cache)."""
    from cardbot.web.cards import card_image  # evita un import circolare
    from cardbot.web.search import image_url

    ids = [i for i in item_ids if i not in _IN_PROGRESS]  # stessa carta già in aggiornamento: non si ripete
    _IN_PROGRESS.update(ids)
    try:
        return await _refresh(sessions, catalog, ids, card_image, image_url)
    finally:
        _IN_PROGRESS.difference_update(ids)


_IN_PROGRESS: set[int] = set()


async def _refresh(sessions: sessionmaker[Session], catalog: Catalog, item_ids: list[int], card_image,
                   image_url) -> int:
    updated = 0
    touched: set[int] = set()
    for item_id in item_ids:
        # La connessione al database non resta occupata mentre si aspetta il catalogo.
        with sessions() as session:
            item = session.get(CollectionItem, item_id)
            key = (item.catalog_lang, item.card_id) if item else None
        if key is None:
            continue
        try:
            card = await catalog.get_card(*key)
            image = await card_image(catalog, key[0], card) if card else None
        except Exception as exc:  # una carta che non risponde non blocca le altre
            log.warning("Carta %s non disponibile: %s", key[1], exc)
            continue
        if card is None:
            continue
        with sessions() as session:
            item = session.get(CollectionItem, item_id)
            if item is None:
                continue
            available = variants_of(card)
            if available and item.variant not in available:
                try:
                    _move_variant(session, item, "holo" if "holo" in available else available[0])
                except _Merged:  # quantità sommata a una riga già esistente: questa non c'è più
                    session.commit()
                    continue
            entry = variant_entry(card, item.variant)
            pricing = (entry or {}).get("pricing") or card.get("pricing") or {}
            cm = pricing.get("cardmarket") or {}
            item.shared_product = _shared_product(card, entry)
            item.id_product = int(cm["idProduct"]) if cm.get("idProduct") else None
            item.unit_price = market_price(cm, item.variant, item.shared_product)
            item.price_updated_at = parse_datetime(cm.get("updated")) or utcnow()
            item.image = image_url(image) or item.image
            item.rarity = card.get("rarity")
            item.dex_ids = ",".join(str(n) for n in card.get("dexId") or [])
            s = card.get("set") or {}
            total = (s.get("cardCount") or {}).get("official")
            item.number_label = f"{card.get('localId', '')}/{total}" if total else card.get("localId")
            item.set_name = s.get("name") or item.set_name
            item.set_id = s.get("id") or item.set_id
            item.name = card.get("name") or item.name
            touched.add(item.collection_id)
            session.commit()
            updated += 1
    with sessions() as session:
        for cid in touched:
            record_value(session, cid)
        session.commit()
    return updated


def _move_variant(session: Session, item: CollectionItem, variant: str) -> None:
    """La variante del file non esiste per questa carta: si sposta su quella giusta (sommando se c'è già)."""
    other = (session.query(CollectionItem)
             .filter_by(collection_id=item.collection_id, catalog_lang=item.catalog_lang, card_id=item.card_id,
                        variant=variant, lang=item.lang).one_or_none())
    if other is not None:
        other.quantity += item.quantity
        session.delete(item)
        session.flush()
        raise _Merged()
    item.variant = variant


class _Merged(Exception):
    pass


# --- valore e storico ---------------------------------------------------------------------------------------

def collection_totals(items: list[CollectionItem]) -> dict[str, Any]:
    priced = [i for i in items if i.unit_price is not None]
    return {
        "value": round(sum(i.unit_price * i.quantity for i in priced), 2),
        "cards": sum(i.quantity for i in items),
        "unique": len(items),
        "unpriced": sum(1 for i in items if i.unit_price is None),
    }


def record_value(session: Session, collection_id: int, day: date | None = None) -> None:
    items = session.query(CollectionItem).filter_by(collection_id=collection_id).all()
    totals = collection_totals(items)
    day = day or today()
    row = session.query(CollectionValue).filter_by(collection_id=collection_id, day=day).one_or_none()
    if row is None:
        row = CollectionValue(collection_id=collection_id, day=day, value=0, cards=0)
        session.add(row)
    row.value, row.cards = totals["value"], totals["cards"]


def history_rows(entry: dict[str, Any]) -> dict[str, dict[str, float | None]]:
    """Campi base e "-holo" di una riga del price guide (0 = nessun dato)."""
    out = {}
    for name, suffix in (("base", ""), ("holo", "-holo")):
        values = {k: (float(entry[f"{k}{suffix}"]) if entry.get(f"{k}{suffix}") else None) for k in CM_FIELDS}
        if any(values.values()):
            out[name] = values
    return out


def update_from_price_guide(session: Session, entries: dict[int, dict[str, Any]], day: date,
                            extra_products: set[int] | None = None) -> dict[str, int]:
    """Job notturno: nuovi prezzi delle carte in collezione, storico giornaliero e valore delle collezioni."""
    items = session.query(CollectionItem).filter(CollectionItem.id_product.isnot(None)).all()
    priced = 0
    for item in items:
        entry = entries.get(item.id_product)
        if entry is None:
            continue
        price = market_price(entry, item.variant, item.shared_product)
        if price is not None:
            item.unit_price, item.price_updated_at = price, utcnow()
            priced += 1
    products = {i.id_product for i in items} | (extra_products or set())
    saved = 0
    for pid in products:
        entry = entries.get(pid)
        if entry is None:
            continue
        for fields, values in history_rows(entry).items():
            row = session.query(PriceHistory).filter_by(id_product=pid, fields=fields, day=day).one_or_none()
            if row is None:
                row = PriceHistory(id_product=pid, fields=fields, day=day)
                session.add(row)
                saved += 1
            for k, v in values.items():
                setattr(row, k, v)
    session.flush()
    for (cid,) in session.query(Collection.id).all():
        record_value(session, cid, day)
    return {"items_priced": priced, "history_rows": saved}


def _eur(x: float) -> str:
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def wishlist_alerts(session: Session) -> list[tuple[int, str]]:
    """Carte della lista desideri scese sotto il prezzo obiettivo: un avviso, poi silenzio finché non risale."""
    rows = (session.query(CollectionItem).join(Collection)
            .filter(Collection.kind == "wishlist", CollectionItem.target_price.isnot(None),
                    CollectionItem.unit_price.isnot(None)).all())
    out: list[tuple[int, str]] = []
    for i in rows:
        if i.unit_price <= i.target_price and i.target_notified_at is None:
            i.target_notified_at = utcnow()
            where = " ".join(x for x in (i.set_name, i.number_label) if x)
            out.append((i.collection.user_id, f"{i.name} ({where}) è a {_eur(i.unit_price)}: sotto i tuoi "
                                              f"{_eur(i.target_price)}"))
        elif i.target_notified_at is not None and i.unit_price > i.target_price * 1.05:
            i.target_notified_at = None  # risalita: il prossimo calo verrà segnalato di nuovo
    return out
