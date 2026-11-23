"""Scambi tra amici: proposta, controproposta, accettazione, conferma di entrambi, spostamento delle carte, annullo.

Quando entrambi confermano di aver ricevuto le carte, ogni carta passa dalla collezione di chi la dà a quella di chi
la riceve (e sparisce dalla sua lista desideri). Ogni spostamento è registrato in `moves`, così "Annulla" riporta
tutto com'era.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from cardbot.accounts import are_friends
from cardbot.collections.service import record_value
from cardbot.db import Collection, CollectionItem, Trade, TradeItem, User, utcnow

UNDO_DAYS = 14
ITEM_FIELDS = ("card_id", "catalog_lang", "variant", "variant_label", "lang", "name", "set_id", "set_name",
               "number_label", "image", "rarity", "id_product", "shared_product", "unit_price", "dex_ids")


class TradeError(ValueError):
    pass


def _collection_item(session: Session, user_id: int, item_id: int, visible_only: bool) -> CollectionItem:
    item = session.get(CollectionItem, item_id)
    col = item.collection if item else None
    if (item is None or col.user_id != user_id or col.kind != "collection"
            or (visible_only and col.visibility != "friends")):
        raise TradeError("Una delle carte non è più disponibile.")
    return item


def create_trade(session: Session, proposer: User, recipient_id: int, give: list[tuple[int, int]],
                 take: list[tuple[int, int]], message: str | None = None, parent_id: int | None = None) -> Trade:
    """give: carte che proponi (tue), take: carte che chiedi (dell'amico); coppie (id carta in collezione, copie)."""
    if recipient_id == proposer.id or not are_friends(session, proposer.id, recipient_id):
        raise TradeError("Puoi proporre scambi solo ai tuoi amici.")
    if not give and not take:
        raise TradeError("Scegli almeno una carta.")
    trade = Trade(proposer_id=proposer.id, recipient_id=recipient_id, status="proposed",
                  message=(message or "").strip()[:500] or None, parent_id=parent_id)
    for owner_id, rows, visible_only in ((proposer.id, give, False), (recipient_id, take, True)):
        for item_id, qty in rows:
            item = _collection_item(session, owner_id, item_id, visible_only)
            if not 1 <= qty <= item.quantity:
                raise TradeError(f"{item.name}: ce ne sono solo {item.quantity}.")
            trade.items.append(TradeItem(from_user_id=owner_id, source_item_id=item.id, quantity=qty,
                                         **{k: getattr(item, k) for k in ("card_id", "catalog_lang", "variant",
                                            "lang", "name", "set_name", "number_label", "image", "unit_price")}))
    if parent_id is not None:
        parent = session.get(Trade, parent_id)
        if parent is None or parent.status != "proposed" or parent.recipient_id != proposer.id:
            raise TradeError("Puoi fare una controproposta solo a una proposta ricevuta e ancora aperta.")
        parent.status, parent.updated_at = "countered", utcnow()
    session.add(trade)
    session.flush()
    return trade


def act(session: Session, trade: Trade, user: User, action: str) -> str:
    """Azioni: accept, reject, cancel, confirm, undo. Restituisce il testo della notifica per l'altro."""
    me_proposer = trade.proposer_id == user.id
    if not me_proposer and trade.recipient_id != user.id:
        raise TradeError("Scambio non trovato.")
    now = utcnow()
    if action in ("accept", "reject"):
        if me_proposer or trade.status != "proposed":
            raise TradeError("Solo chi riceve la proposta può accettarla o rifiutarla.")
        _check_still_available(session, trade) if action == "accept" else None
        trade.status = "accepted" if action == "accept" else "rejected"
        text = "ha accettato la tua proposta di scambio" if action == "accept" else "ha rifiutato la tua proposta"
    elif action == "cancel":
        if trade.status not in ("proposed", "accepted"):
            raise TradeError("Questo scambio non si può più ritirare.")
        trade.status = "cancelled"
        text = "ha annullato lo scambio"
    elif action == "confirm":
        if trade.status != "accepted":
            raise TradeError("Si conferma solo uno scambio accettato.")
        if me_proposer:
            trade.proposer_confirmed_at = now
        else:
            trade.recipient_confirmed_at = now
        text = "ha confermato di aver ricevuto le carte"
        if trade.proposer_confirmed_at and trade.recipient_confirmed_at:
            _check_still_available(session, trade)
            trade.moves = _move_cards(session, trade)
            trade.status = "completed"
            text = "ha confermato: scambio completato, le carte sono nelle vostre collezioni"
    elif action == "undo":
        if trade.status != "completed" or now - _aware(trade.updated_at) > timedelta(days=UNDO_DAYS):
            raise TradeError(f"Si può annullare solo uno scambio completato da meno di {UNDO_DAYS} giorni.")
        _undo_moves(session, trade.moves or [])
        trade.status = "undone"
        text = "ha annullato lo scambio completato: le carte sono tornate com'erano"
    else:
        raise TradeError("Azione sconosciuta.")
    trade.updated_at = now
    session.flush()
    return text


def _aware(dt):
    from datetime import UTC
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _find_source(session: Session, ti: TradeItem) -> CollectionItem | None:
    item = session.get(CollectionItem, ti.source_item_id) if ti.source_item_id else None
    if item is not None and item.collection.user_id == ti.from_user_id and item.card_id == ti.card_id:
        return item
    return (session.query(CollectionItem).join(Collection)
            .filter(Collection.user_id == ti.from_user_id, Collection.kind == "collection",
                    CollectionItem.card_id == ti.card_id, CollectionItem.catalog_lang == ti.catalog_lang,
                    CollectionItem.variant == ti.variant).first())


def _check_still_available(session: Session, trade: Trade) -> None:
    for ti in trade.items:
        src = _find_source(session, ti)
        if src is None or src.quantity < ti.quantity:
            raise TradeError(f"{ti.name}: la carta non è più nella collezione di chi la dà.")


def _default_collection(session: Session, user_id: int) -> Collection:
    col = (session.query(Collection).filter_by(user_id=user_id, kind="collection")
           .order_by(Collection.id).first())
    if col is None:
        col = Collection(user_id=user_id, name="La mia collezione")
        session.add(col)
        session.flush()
    return col


def _move_cards(session: Session, trade: Trade) -> list[dict[str, Any]]:
    moves: list[dict[str, Any]] = []
    touched: set[int] = set()
    for ti in trade.items:
        to_user = trade.recipient_id if ti.from_user_id == trade.proposer_id else trade.proposer_id
        src = _find_source(session, ti)
        data = {k: getattr(src, k) for k in ITEM_FIELDS}
        src.quantity -= ti.quantity
        moves.append({"op": "remove", "collection_id": src.collection_id, "qty": ti.quantity, "item": data,
                      "deleted": src.quantity <= 0, "item_id": src.id})
        touched.add(src.collection_id)
        if src.quantity <= 0:
            session.delete(src)
        dest = _default_collection(session, to_user)
        existing = (session.query(CollectionItem)
                    .filter_by(collection_id=dest.id, catalog_lang=ti.catalog_lang, card_id=ti.card_id,
                               variant=ti.variant, lang=ti.lang).one_or_none())
        if existing is None:
            existing = CollectionItem(collection_id=dest.id, quantity=0, needs_review=False, source="scambio",
                                      **data)
            session.add(existing)
            session.flush()
            created = True
        else:
            created = False
        existing.quantity += ti.quantity
        moves.append({"op": "add", "collection_id": dest.id, "item_id": existing.id, "qty": ti.quantity,
                      "created": created})
        touched.add(dest.id)
        # Ricevuta: non serve più nella lista desideri.
        wish = (session.query(CollectionItem).join(Collection)
                .filter(Collection.user_id == to_user, Collection.kind == "wishlist",
                        CollectionItem.card_id == ti.card_id, CollectionItem.catalog_lang == ti.catalog_lang).first())
        if wish is not None:
            moves.append({"op": "unwish", "collection_id": wish.collection_id, "qty": wish.quantity,
                          "item": {k: getattr(wish, k) for k in ITEM_FIELDS} | {"target_price": wish.target_price}})
            session.delete(wish)
        session.flush()
    for cid in touched:
        record_value(session, cid)
    return moves


def _undo_moves(session: Session, moves: list[dict[str, Any]]) -> None:
    touched: set[int] = set()
    for m in reversed(moves):
        touched.add(m["collection_id"])
        if m["op"] == "add":
            item = session.get(CollectionItem, m["item_id"])
            if item is not None:
                item.quantity -= m["qty"]
                if item.quantity <= 0:
                    session.delete(item)
        else:  # remove / unwish: la carta torna dove era
            data = dict(m["item"])
            target = data.pop("target_price", None)
            item = (session.query(CollectionItem)
                    .filter_by(collection_id=m["collection_id"], catalog_lang=data["catalog_lang"],
                               card_id=data["card_id"], variant=data["variant"], lang=data["lang"]).one_or_none())
            if item is None:
                item = CollectionItem(collection_id=m["collection_id"], quantity=0, needs_review=False,
                                      source="scambio", target_price=target, **data)
                session.add(item)
            item.quantity += m["qty"]
        session.flush()
    for cid in touched:
        if session.get(Collection, cid) is not None:
            record_value(session, cid)


def trade_json(trade: Trade, me: User, names: dict[int, str]) -> dict[str, Any]:
    other = trade.recipient_id if trade.proposer_id == me.id else trade.proposer_id

    def side(uid: int) -> list[dict[str, Any]]:
        return [{"id": i.id, "card_id": i.card_id, "catalog_lang": i.catalog_lang, "name": i.name,
                 "set_name": i.set_name, "number_label": i.number_label, "image": i.image, "variant": i.variant,
                 "lang": i.lang, "quantity": i.quantity, "unit_price": i.unit_price,
                 "total": round(i.unit_price * i.quantity, 2) if i.unit_price is not None else None}
                for i in trade.items if i.from_user_id == uid]

    give, take = side(me.id), side(other)
    mine_confirmed = trade.proposer_confirmed_at if trade.proposer_id == me.id else trade.recipient_confirmed_at
    theirs_confirmed = trade.recipient_confirmed_at if trade.proposer_id == me.id else trade.proposer_confirmed_at
    return {
        "id": trade.id, "status": trade.status, "role": "proposer" if trade.proposer_id == me.id else "recipient",
        "other": {"id": other, "name": names.get(other, "Amico")}, "message": trade.message,
        "parent_id": trade.parent_id, "give": give, "take": take,
        "give_value": round(sum(x["total"] or 0 for x in give), 2),
        "take_value": round(sum(x["total"] or 0 for x in take), 2),
        "i_confirmed": bool(mine_confirmed), "they_confirmed": bool(theirs_confirmed),
        "created_at": trade.created_at.isoformat(), "updated_at": trade.updated_at.isoformat(),
        "can_undo": trade.status == "completed" and utcnow() - _aware(trade.updated_at) <= timedelta(days=UNDO_DAYS),
    }


def needs_my_action(trade: Trade, me: User) -> bool:
    if trade.status == "proposed":
        return trade.recipient_id == me.id
    if trade.status == "accepted":
        mine = trade.proposer_confirmed_at if trade.proposer_id == me.id else trade.recipient_confirmed_at
        return mine is None
    return False
