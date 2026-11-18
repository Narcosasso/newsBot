"""API delle collezioni: elenco, dettaglio con valore e storico, import da file, aggiunta dalla scheda carta."""

from __future__ import annotations

import json
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cardbot.collections.importer import CollectionImporter, ImportFormatError, parse_export
from cardbot.collections.service import (
    apply_plan, collection_totals, get_or_create_collection, record_value, refresh_items, upsert_item,
)
from cardbot.db import Collection, CollectionItem, CollectionValue, User
from cardbot.langs import LANGS

MAX_IMPORT_BYTES = 5 * 1024 * 1024
VARIANTS = ("normal", "holo", "reverse")


class CollectionBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ItemBody(BaseModel):
    collection_id: int | None = None
    card_id: str = Field(max_length=64)
    catalog_lang: str = Field(max_length=8)
    variant: str = Field(max_length=16)
    lang: str = Field(max_length=8)
    quantity: int = Field(ge=0, le=999)


def item_json(i: CollectionItem) -> dict[str, Any]:
    return {
        "id": i.id, "collection_id": i.collection_id, "card_id": i.card_id, "catalog_lang": i.catalog_lang,
        "name": i.name, "set_id": i.set_id, "set_name": i.set_name, "number_label": i.number_label,
        "image": i.image, "rarity": i.rarity, "variant": i.variant, "variant_label": i.variant_label,
        "lang": i.lang, "quantity": i.quantity, "unit_price": i.unit_price,
        "total": round(i.unit_price * i.quantity, 2) if i.unit_price is not None else None,
        "needs_review": i.needs_review, "added_at": i.added_at.isoformat() if i.added_at else None,
    }


def add_collection_routes(router: APIRouter, current_user: Callable, db: Callable, container: Callable) -> None:

    def owned(session: Session, user: User, collection_id: int) -> Collection:
        col = session.get(Collection, collection_id)
        if col is None or col.user_id != user.id:
            raise HTTPException(404, "Collezione non trovata")
        return col

    def default_collection(session: Session, user: User) -> Collection:
        first = session.query(Collection).filter_by(user_id=user.id).order_by(Collection.id).first()
        return first or get_or_create_collection(session, user, "La mia collezione")

    @router.get("/collections")
    def list_collections(user: User = Depends(current_user), session: Session = Depends(db)) -> dict[str, Any]:
        out = []
        for col in session.query(Collection).filter_by(user_id=user.id).order_by(Collection.id).all():
            out.append({"id": col.id, "name": col.name, **collection_totals(col.items)})
        return {"collections": out}

    @router.post("/collections")
    def create_collection(body: CollectionBody, user: User = Depends(current_user),
                          session: Session = Depends(db)) -> dict[str, Any]:
        col = get_or_create_collection(session, user, body.name.strip())
        session.commit()
        return {"id": col.id, "name": col.name}

    @router.patch("/collections/{collection_id}")
    def rename_collection(collection_id: int, body: CollectionBody, user: User = Depends(current_user),
                          session: Session = Depends(db)) -> dict[str, Any]:
        col = owned(session, user, collection_id)
        col.name = body.name.strip()
        session.commit()
        return {"id": col.id, "name": col.name}

    @router.delete("/collections/{collection_id}")
    def delete_collection(collection_id: int, user: User = Depends(current_user),
                          session: Session = Depends(db)) -> dict[str, Any]:
        col = owned(session, user, collection_id)
        session.query(CollectionValue).filter_by(collection_id=col.id).delete()
        session.delete(col)
        session.commit()
        return {"ok": True}

    @router.get("/collections/{collection_id}")
    def get_collection(collection_id: int, user: User = Depends(current_user),
                       session: Session = Depends(db)) -> dict[str, Any]:
        col = owned(session, user, collection_id)
        history = (session.query(CollectionValue).filter_by(collection_id=col.id)
                   .order_by(CollectionValue.day).all())
        items = sorted(col.items, key=lambda i: -(i.unit_price or 0) * i.quantity)
        return {"id": col.id, "name": col.name, **collection_totals(col.items),
                "history": [{"day": h.day.isoformat(), "value": h.value, "cards": h.cards} for h in history],
                "items": [item_json(i) for i in items],
                "pending_prices": sum(1 for i in col.items if i.price_updated_at is None)}

    @router.post("/collections/{collection_id}/refresh")
    def refresh_collection(collection_id: int, tasks: BackgroundTasks, user: User = Depends(current_user),
                           session: Session = Depends(db), c=Depends(container)) -> dict[str, Any]:
        col = owned(session, user, collection_id)
        ids = [i.id for i in col.items]
        tasks.add_task(refresh_items, c.sessions, c.catalog, ids)
        return {"ok": True, "items": len(ids)}

    @router.post("/collections/import")
    async def import_collection(request: Request, tasks: BackgroundTasks, name: str | None = None,
                                user: User = Depends(current_user), session: Session = Depends(db),
                                c=Depends(container)) -> dict[str, Any]:
        raw = await request.body()
        if not raw or len(raw) > MAX_IMPORT_BYTES:
            raise HTTPException(413, "File mancante o troppo grande (massimo 5 MB).")
        try:
            data = json.loads(raw)
            collection_name, rows = parse_export(data)
        except (ValueError, ImportFormatError) as exc:
            msg = str(exc) if isinstance(exc, ImportFormatError) else "Il file non è un JSON valido."
            raise HTTPException(422, msg) from exc
        plan = await CollectionImporter(c.catalog).plan(collection_name, rows)
        report = apply_plan(session, user, plan, (name or "").strip() or None)
        # Immagini e prezzi si completano dopo la risposta: una richiesta al catalogo per carta.
        tasks.add_task(refresh_items, c.sessions, c.catalog, report.item_ids)
        return {"collection_id": report.collection_id, "collection_name": report.collection_name,
                "imported": report.imported, "cards": report.cards, "review": report.review,
                "unmatched": report.unmatched}

    @router.put("/collection-items")
    async def put_item(body: ItemBody, user: User = Depends(current_user), session: Session = Depends(db),
                       c=Depends(container)) -> dict[str, Any]:
        if body.variant not in VARIANTS or body.lang not in LANGS:
            raise HTTPException(422, "Variante o lingua non valida")
        col = owned(session, user, body.collection_id) if body.collection_id else default_collection(session, user)
        card = await c.catalog.get_card(body.catalog_lang, body.card_id)
        if card is None:
            raise HTTPException(404, "Carta non trovata")
        existing = (session.query(CollectionItem)
                    .filter_by(collection_id=col.id, catalog_lang=body.catalog_lang, card_id=body.card_id,
                               variant=body.variant, lang=body.lang).one_or_none())
        if body.quantity == 0:
            if existing is not None:
                session.delete(existing)
                session.flush()
                record_value(session, col.id)
                session.commit()
            return {"item": None, "owned": owned_for(session, user, body.card_id, body.catalog_lang)}
        item = upsert_item(session, col, card_id=body.card_id, catalog_lang=body.catalog_lang,
                           variant=body.variant, lang=body.lang, quantity=body.quantity,
                           name=card.get("name", ""), source="app")
        item.needs_review = False
        session.commit()
        item_id = item.id
        await refresh_items(c.sessions, c.catalog, [item_id])  # una sola carta: prezzo subito
        session.expire_all()
        return {"item": item_json(session.get(CollectionItem, item_id)),
                "owned": owned_for(session, user, body.card_id, body.catalog_lang)}

    @router.post("/collection-items/{item_id}/confirm")
    def confirm_item(item_id: int, user: User = Depends(current_user),
                     session: Session = Depends(db)) -> dict[str, Any]:
        item = session.get(CollectionItem, item_id)
        if item is None or item.collection.user_id != user.id:
            raise HTTPException(404, "Non trovato")
        item.needs_review = False
        session.commit()
        return {"ok": True}

    @router.delete("/collection-items/{item_id}")
    def delete_item(item_id: int, user: User = Depends(current_user),
                    session: Session = Depends(db)) -> dict[str, Any]:
        item = session.get(CollectionItem, item_id)
        if item is None or item.collection.user_id != user.id:
            raise HTTPException(404, "Non trovato")
        cid = item.collection_id
        session.delete(item)
        session.flush()
        record_value(session, cid)
        session.commit()
        return {"ok": True}


def owned_for(session: Session, user: User, card_id: str, catalog_lang: str) -> list[dict[str, Any]]:
    """Copie della carta che possiedi, in tutte le collezioni."""
    rows = (session.query(CollectionItem).join(Collection)
            .filter(Collection.user_id == user.id, CollectionItem.card_id == card_id,
                    CollectionItem.catalog_lang == catalog_lang).all())
    return [{**item_json(i), "collection_name": i.collection.name} for i in rows]
