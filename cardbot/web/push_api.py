"""API delle notifiche push: chiave pubblica, iscrizione del dispositivo, prova."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cardbot.db import PushSubscription, User


class SubKeys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class SubBody(BaseModel):
    endpoint: str = Field(max_length=600)
    keys: SubKeys


class EndpointBody(BaseModel):
    endpoint: str = Field(max_length=600)


def add_push_routes(router: APIRouter, current_user: Callable, db: Callable, container: Callable) -> None:

    @router.get("/push/key")
    def push_key(user: User = Depends(current_user), c=Depends(container)) -> dict[str, Any]:
        return {"public_key": c.push.keys().public_key}

    @router.get("/push/status")
    def push_status(endpoint: str = "", user: User = Depends(current_user),
                    session: Session = Depends(db)) -> dict[str, Any]:
        subs = session.query(PushSubscription).filter_by(user_id=user.id).all()
        return {"devices": len(subs), "this_device": any(s.endpoint == endpoint for s in subs)}

    @router.post("/push/subscribe")
    def subscribe(body: SubBody, request: Request, user: User = Depends(current_user),
                  session: Session = Depends(db)) -> dict[str, Any]:
        if not body.endpoint.startswith("https://"):
            raise HTTPException(422, "Iscrizione non valida")
        sub = session.query(PushSubscription).filter_by(endpoint=body.endpoint).one_or_none()
        if sub is None:
            sub = PushSubscription(endpoint=body.endpoint, user_id=user.id, p256dh="", auth="", failures=0)
            session.add(sub)
        sub.user_id, sub.p256dh, sub.auth = user.id, body.keys.p256dh, body.keys.auth
        sub.user_agent = (request.headers.get("user-agent") or "")[:300]
        session.commit()
        return {"ok": True}

    @router.post("/push/unsubscribe")
    def unsubscribe(body: EndpointBody, user: User = Depends(current_user),
                    session: Session = Depends(db)) -> dict[str, Any]:
        session.query(PushSubscription).filter_by(endpoint=body.endpoint, user_id=user.id).delete()
        session.commit()
        return {"ok": True}

    @router.post("/push/test")
    async def test(user: User = Depends(current_user), c=Depends(container)) -> dict[str, Any]:
        sent = await c.push.send_to_user(user.id, "PokeVault", "Le notifiche funzionano: qui arriveranno gli avvisi "
                                         "sui prezzi delle tue carte.", tag="prova")
        if not sent:
            raise HTTPException(502, "Notifica non consegnata: riattiva le notifiche su questo telefono.")
        return {"sent": sent}
