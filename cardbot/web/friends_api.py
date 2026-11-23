"""API di amici, inviti, collezioni degli amici, incroci desideri/doppioni e scambi."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from cardbot.accounts import (
    PIN_RE, are_friends, befriend, display_name, hash_pin, user_by_pin, wishlist_of,
)
from cardbot.collections.service import collection_totals, get_or_create_collection
from cardbot.db import Collection, CollectionItem, Friendship, Invite, Trade, User, utcnow
from cardbot.trades import TradeError, act, create_trade, needs_my_action, trade_json
from cardbot.web.collections_api import item_json

INVITE_DAYS = 7


class NameBody(BaseModel):
    name: str = Field(min_length=2, max_length=30)


class AcceptBody(BaseModel):
    name: str = Field(min_length=2, max_length=30)
    pin: str = Field(max_length=12)


class PrivacyBody(BaseModel):
    visibility: str | None = Field(default=None, pattern="^(friends|private)$")
    show_values: bool | None = None


class Pick(BaseModel):
    item_id: int
    quantity: int = Field(default=1, ge=1, le=99)


class TradeBody(BaseModel):
    friend_id: int
    give: list[Pick] = Field(default_factory=list, max_length=40)
    take: list[Pick] = Field(default_factory=list, max_length=40)
    message: str | None = Field(default=None, max_length=500)
    parent_id: int | None = None


def _aware(dt):
    from datetime import UTC
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def add_friend_routes(router: APIRouter, current_user: Callable, db: Callable, container: Callable,
                      start_session: Callable, guard: Any) -> None:

    def names(session: Session, c, ids: set[int]) -> dict[int, str]:
        return {u.id: display_name(u, c.settings) for u in session.query(User).filter(User.id.in_(ids)).all()}

    async def notify(c, user_id: int, body: str, url: str = "/#/friends") -> None:
        try:
            await c.push.send_to_user(user_id, "PokeVault · scambi", body, url=url, tag="scambi")
        except Exception:  # la notifica è un di più: l'azione è già salvata
            pass

    def friend_or_404(session: Session, user: User, friend_id: int) -> User:
        friend = session.get(User, friend_id)
        if friend is None or not are_friends(session, user.id, friend_id):
            raise HTTPException(404, "Amico non trovato")
        return friend

    def visible_items(session: Session, owner_id: int, kind: str) -> list[CollectionItem]:
        return (session.query(CollectionItem).join(Collection)
                .filter(Collection.user_id == owner_id, Collection.kind == kind,
                        Collection.visibility == "friends").all())

    def my_items(session: Session, user_id: int, kind: str) -> list[CollectionItem]:
        return (session.query(CollectionItem).join(Collection)
                .filter(Collection.user_id == user_id, Collection.kind == kind).all())

    def matches(session: Session, me: User, friend_id: int) -> dict[str, list[CollectionItem]]:
        """they_have: sue carte che cerchi; you_have: tue carte che cerca (prima i doppioni)."""
        mine_wish = {(i.catalog_lang, i.card_id) for i in my_items(session, me.id, "wishlist")}
        their_wish = {(i.catalog_lang, i.card_id) for i in visible_items(session, friend_id, "wishlist")}
        they = [i for i in visible_items(session, friend_id, "collection") if (i.catalog_lang, i.card_id) in mine_wish]
        you = [i for i in my_items(session, me.id, "collection") if (i.catalog_lang, i.card_id) in their_wish]
        you.sort(key=lambda i: (i.quantity <= 1, i.name))
        return {"they_have": they, "you_have": you}

    def public_item(i: CollectionItem, show_values: bool) -> dict[str, Any]:
        d = item_json(i)
        if not show_values:
            d["unit_price"] = d["total"] = None
        return d

    # --- profilo --------------------------------------------------------------------------------------------

    @router.patch("/me")
    def rename(body: NameBody, user: User = Depends(current_user), session: Session = Depends(db),
               c=Depends(container)) -> dict[str, Any]:
        user.display_name = body.name.strip()
        session.commit()
        return {"name": display_name(user, c.settings)}

    # --- inviti -----------------------------------------------------------------------------------------------

    @router.post("/invites")
    def create_invite(user: User = Depends(current_user), session: Session = Depends(db)) -> dict[str, Any]:
        inv = Invite(code=secrets.token_urlsafe(16), created_by=user.id,
                     expires_at=utcnow() + timedelta(days=INVITE_DAYS))
        session.add(inv)
        session.commit()
        return {"code": inv.code, "path": f"/#/invite/{inv.code}", "expires_at": inv.expires_at.isoformat()}

    def open_invite(session: Session, code: str) -> Invite:
        inv = session.query(Invite).filter_by(code=code).one_or_none()
        if inv is None or inv.used_by is not None or _aware(inv.expires_at) < utcnow():
            raise HTTPException(404, "Invito non valido o già usato: chiedine uno nuovo.")
        return inv

    @router.get("/invites/{code}")
    def invite_info(code: str, session: Session = Depends(db), c=Depends(container)) -> dict[str, Any]:
        inv = open_invite(session, code)
        return {"inviter": display_name(session.get(User, inv.created_by), c.settings)}

    @router.post("/invites/{code}/accept")
    def accept_invite(code: str, body: AcceptBody, request: Request, response: Response,
                      session: Session = Depends(db), c=Depends(container)) -> dict[str, Any]:
        guard.check()
        inv = open_invite(session, code)
        pin = body.pin.strip()
        if not PIN_RE.match(pin):
            raise HTTPException(422, "Il PIN deve avere da 6 a 12 cifre.")
        if pin == c.settings.app_pin or user_by_pin(session, pin) is not None:
            raise HTTPException(422, "Questo PIN è già usato da qualcuno: scegline un altro.")
        user = User(wa_id=f"app:{secrets.token_hex(8)}", display_name=body.name.strip(), pin_hash=hash_pin(pin),
                    invited_by=inv.created_by)
        session.add(user)
        session.flush()
        befriend(session, user.id, inv.created_by)
        get_or_create_collection(session, user, "La mia collezione")
        wishlist_of(session, user)
        inv.used_by, inv.used_at = user.id, utcnow()
        session.commit()
        start_session(session, user, request, response)
        return {"ok": True, "name": user.display_name}

    # --- amici e loro collezioni ------------------------------------------------------------------------------

    @router.get("/friends")
    def list_friends(user: User = Depends(current_user), session: Session = Depends(db),
                     c=Depends(container)) -> dict[str, Any]:
        out = []
        ids = [f for (f,) in session.query(Friendship.friend_id).filter_by(user_id=user.id).all()]
        for friend in session.query(User).filter(User.id.in_(ids)).all():
            cols = (session.query(Collection).filter_by(user_id=friend.id, visibility="friends")
                    .order_by(Collection.kind, Collection.id).all())
            m = matches(session, user, friend.id)
            owned = [i for col in cols if col.kind == "collection" for i in col.items]
            out.append({
                "id": friend.id, "name": display_name(friend, c.settings),
                "cards": sum(i.quantity for i in owned), "unique": len(owned),
                "collections": [{"id": col.id, "name": col.name, "kind": col.kind,
                                 **{k: v for k, v in collection_totals(col.items).items()
                                    if col.show_values or k != "value"}} for col in cols],
                "they_have": len(m["they_have"]), "you_have": len(m["you_have"]),
            })
        out.sort(key=lambda f: f["name"].lower())
        return {"friends": out}

    @router.delete("/friends/{friend_id}")
    def remove_friend(friend_id: int, user: User = Depends(current_user),
                      session: Session = Depends(db)) -> dict[str, Any]:
        session.query(Friendship).filter(
            or_((Friendship.user_id == user.id) & (Friendship.friend_id == friend_id),
                (Friendship.user_id == friend_id) & (Friendship.friend_id == user.id))).delete()
        session.commit()
        return {"ok": True}

    @router.get("/friends/{friend_id}/collections/{collection_id}")
    def friend_collection(friend_id: int, collection_id: int, user: User = Depends(current_user),
                          session: Session = Depends(db), c=Depends(container)) -> dict[str, Any]:
        friend = friend_or_404(session, user, friend_id)
        col = session.get(Collection, collection_id)
        if col is None or col.user_id != friend.id or col.visibility != "friends":
            raise HTTPException(404, "Collezione non visibile")
        mine = {(i.catalog_lang, i.card_id) for i in my_items(session, user.id, "collection")}
        wish = {(i.catalog_lang, i.card_id) for i in my_items(session, user.id, "wishlist")}
        items = []
        for i in sorted(col.items, key=lambda i: i.name):
            d = public_item(i, col.show_values)
            d["i_have"] = (i.catalog_lang, i.card_id) in mine
            d["i_want"] = (i.catalog_lang, i.card_id) in wish
            items.append(d)
        totals = collection_totals(col.items)
        if not col.show_values:
            totals.pop("value")
        return {"id": col.id, "name": col.name, "kind": col.kind, "friend": display_name(friend, c.settings),
                "show_values": col.show_values, **totals, "items": items}

    @router.get("/friends/{friend_id}/matches")
    def friend_matches(friend_id: int, user: User = Depends(current_user), session: Session = Depends(db),
                       c=Depends(container)) -> dict[str, Any]:
        friend = friend_or_404(session, user, friend_id)
        m = matches(session, user, friend.id)
        # Nello scambio i prezzi di mercato servono a capire se è equilibrato: sono quelli pubblici di Cardmarket.
        return {"friend": display_name(friend, c.settings),
                "they_have": [item_json(i) for i in m["they_have"]],
                "you_have": [item_json(i) for i in m["you_have"]]}

    @router.get("/friends/{friend_id}/tradeable")
    def tradeable(friend_id: int, user: User = Depends(current_user), session: Session = Depends(db)) -> dict[str, Any]:
        """Carte che si possono mettere in uno scambio: tutte quelle visibili dell'amico e tutte le tue."""
        friend_or_404(session, user, friend_id)
        theirs = visible_items(session, friend_id, "collection")
        mine = my_items(session, user.id, "collection")
        return {"theirs": [item_json(i) for i in sorted(theirs, key=lambda i: i.name)],
                "mine": [item_json(i) for i in sorted(mine, key=lambda i: (i.quantity <= 1, i.name))]}

    # --- privacy delle proprie collezioni ---------------------------------------------------------------------

    @router.patch("/collections/{collection_id}/privacy")
    def privacy(collection_id: int, body: PrivacyBody, user: User = Depends(current_user),
                session: Session = Depends(db)) -> dict[str, Any]:
        col = session.get(Collection, collection_id)
        if col is None or col.user_id != user.id:
            raise HTTPException(404, "Collezione non trovata")
        if body.visibility is not None:
            col.visibility = body.visibility
        if body.show_values is not None:
            col.show_values = body.show_values
        session.commit()
        return {"visibility": col.visibility, "show_values": col.show_values}

    # --- scambi -----------------------------------------------------------------------------------------------

    @router.get("/trades")
    def list_trades(user: User = Depends(current_user), session: Session = Depends(db),
                    c=Depends(container)) -> dict[str, Any]:
        rows = (session.query(Trade).filter(or_(Trade.proposer_id == user.id, Trade.recipient_id == user.id))
                .order_by(Trade.updated_at.desc()).limit(100).all())
        who = names(session, c, {t.proposer_id for t in rows} | {t.recipient_id for t in rows})
        return {"trades": [{**trade_json(t, user, who), "needs_me": needs_my_action(t, user)} for t in rows],
                "pending": sum(1 for t in rows if needs_my_action(t, user))}

    @router.post("/trades")
    async def propose(body: TradeBody, user: User = Depends(current_user), session: Session = Depends(db),
                      c=Depends(container)) -> dict[str, Any]:
        try:
            trade = create_trade(session, user, body.friend_id, [(p.item_id, p.quantity) for p in body.give],
                                 [(p.item_id, p.quantity) for p in body.take], body.message, body.parent_id)
        except TradeError as exc:
            raise HTTPException(422, str(exc)) from exc
        session.commit()
        who = names(session, c, {user.id, body.friend_id})
        verb = "ti ha fatto una controproposta" if body.parent_id else "ti ha proposto uno scambio"
        await notify(c, body.friend_id, f"{who[user.id]} {verb}")
        return {"trade": trade_json(trade, user, who)}

    @router.post("/trades/{trade_id}/{action}")
    async def trade_action(trade_id: int, action: str, user: User = Depends(current_user),
                           session: Session = Depends(db), c=Depends(container)) -> dict[str, Any]:
        trade = session.get(Trade, trade_id)
        if trade is None or user.id not in (trade.proposer_id, trade.recipient_id):
            raise HTTPException(404, "Scambio non trovato")
        try:
            text = act(session, trade, user, action)
        except TradeError as exc:
            session.rollback()
            raise HTTPException(422, str(exc)) from exc
        session.commit()
        other = trade.recipient_id if trade.proposer_id == user.id else trade.proposer_id
        who = names(session, c, {user.id, other})
        await notify(c, other, f"{who[user.id]} {text}")
        return {"trade": trade_json(trade, user, who)}
