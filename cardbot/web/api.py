"""API dell'app PokeVault (/api/...). Accesso con PIN, poi cookie di sessione."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import deque
from datetime import timedelta
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cardbot.alerts.tracking import CARDMARKET, PSA10, graded_specs, target_specs, upsert_tracking
from cardbot.db import AppSession, RecentView, Tracking, User, get_or_create_user, utcnow
from cardbot.langs import LANGS
from cardbot.recognition.vision import VisionError
from cardbot.web.cards import card_detail, card_image, card_label, graded_detail
from cardbot.web.analysis import card_analysis
from cardbot.web.collections_api import add_collection_routes, owned_for
from cardbot.web.search import image_url, search, summary

COOKIE = "pv_session"
SESSION_DAYS = 400               # i browser limitano i cookie a circa 400 giorni
MAX_FAILURES, LOCK_SECONDS = 5, 15 * 60
MAX_RECENT = 30
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class LoginGuard:
    """Blocca i tentativi di indovinare il PIN: dopo 5 errori in 15 minuti, stop per 15 minuti."""

    def __init__(self) -> None:
        self.failures: deque[float] = deque()
        self.locked_until = 0.0

    def check(self) -> None:
        if time.monotonic() < self.locked_until:
            raise HTTPException(429, "Troppi tentativi: riprova tra qualche minuto.")

    def fail(self) -> None:
        now = time.monotonic()
        self.failures.append(now)
        while self.failures and self.failures[0] < now - LOCK_SECONDS:
            self.failures.popleft()
        if len(self.failures) >= MAX_FAILURES:
            self.locked_until = now + LOCK_SECONDS
            self.failures.clear()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class LoginBody(BaseModel):
    pin: str = Field(max_length=64)


class TrackBody(BaseModel):
    card_id: str = Field(max_length=64)
    catalog_lang: str = Field(max_length=8)
    variant: str = Field(max_length=16)
    langs: list[str] = Field(default_factory=lambda: ["it"], max_length=9)
    psa: bool = False


def build_api(get_container: Callable[[], Any]) -> APIRouter:
    router = APIRouter(prefix="/api")
    guard = LoginGuard()

    def container() -> Any:
        return get_container()

    def db(c=Depends(container)):
        with c.sessions() as session:
            yield session

    def app_user(session: Session, c) -> User:
        wa_id = c.settings.app_wa_id or next(iter(sorted(c.settings.allowed_wa_id_set)), "app")
        user, _ = get_or_create_user(session, wa_id)
        return user

    def current_user(request: Request, session: Session = Depends(db)) -> User:
        token = request.cookies.get(COOKIE)
        row = session.query(AppSession).filter_by(token_hash=_hash(token)).one_or_none() if token else None
        if row is None:
            raise HTTPException(401, "Accesso richiesto")
        if utcnow() - _aware(row.last_seen_at) > timedelta(hours=1):
            row.last_seen_at = utcnow()
            session.commit()
        return session.get(User, row.user_id)

    # --- accesso ---------------------------------------------------------------------------------------

    @router.post("/login")
    def login(body: LoginBody, request: Request, response: Response, session: Session = Depends(db),
              c=Depends(container)) -> dict[str, Any]:
        pin = c.settings.app_pin
        if not pin:
            raise HTTPException(503, "App non configurata: manca APP_PIN.")
        guard.check()
        if not hmac.compare_digest(body.pin.strip().encode(), pin.encode()):
            guard.fail()
            raise HTTPException(401, "PIN errato")
        user = app_user(session, c)
        token = secrets.token_urlsafe(32)
        session.add(AppSession(token_hash=_hash(token), user_id=user.id,
                               user_agent=(request.headers.get("user-agent") or "")[:300]))
        session.commit()
        response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, samesite="strict",
                            secure=request.url.scheme == "https", path="/")
        return {"ok": True}

    @router.post("/logout")
    def logout(request: Request, response: Response, session: Session = Depends(db)) -> dict[str, Any]:
        token = request.cookies.get(COOKIE)
        if token:
            session.query(AppSession).filter_by(token_hash=_hash(token)).delete()
            session.commit()
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @router.get("/me")
    def me(user: User = Depends(current_user), c=Depends(container)) -> dict[str, Any]:
        return {"app": "PokeVault", "photos": getattr(c.reader, "enabled", False),
                "graded": c.prices.graded_enabled, "langs": [{"code": k, "short": v[0], "flag": v[1]}
                                                              for k, v in LANGS.items()]}

    # --- ricerca e carte ------------------------------------------------------------------------------

    @router.get("/search")
    async def do_search(q: str = "", lang: str = "all", user: User = Depends(current_user),
                        c=Depends(container)) -> dict[str, Any]:
        return {"cards": await search(c.catalog, c.matcher, q[:100], lang)}

    @router.get("/recent")
    def recent(user: User = Depends(current_user), session: Session = Depends(db)) -> dict[str, Any]:
        rows = (session.query(RecentView).filter_by(user_id=user.id).order_by(RecentView.viewed_at.desc())
                .limit(MAX_RECENT).all())
        return {"cards": [{"id": r.card_id, "catalog_lang": r.catalog_lang, "name": r.name, "image": r.image,
                           "set_name": r.set_name} for r in rows]}

    @router.get("/cards/{lang}/{card_id}")
    async def card(lang: str, card_id: str, user: User = Depends(current_user), session: Session = Depends(db),
                   c=Depends(container)) -> dict[str, Any]:
        detail = await card_detail(c.catalog, c.prices, lang, card_id)
        if detail is None:
            raise HTTPException(404, "Carta non trovata")
        _remember(session, user, detail)
        detail["tracking"] = _tracking_for(session, user, card_id, lang)
        detail["owned"] = owned_for(session, user, card_id, lang)
        if not detail["image"]:  # il catalogo non ha la foto: quella salvata in collezione (es. dal file importato)
            photo = next((o["image"] for o in detail["owned"] if o["image"]), None)
            detail["image"] = detail["image_small"] = photo
        return detail

    @router.get("/cards/{lang}/{card_id}/graded")
    async def graded(lang: str, card_id: str, variant: str = "holo", user: User = Depends(current_user),
                     c=Depends(container)) -> dict[str, Any]:
        return await graded_detail(c.prices, c.fx, lang, card_id, variant)

    @router.get("/cards/{lang}/{card_id}/analysis")
    async def analysis(lang: str, card_id: str, variant: str = "holo", user: User = Depends(current_user),
                       session: Session = Depends(db), c=Depends(container)) -> dict[str, Any]:
        return await card_analysis(session, c.catalog, c.prices, lang, card_id, variant)

    # --- scansione ------------------------------------------------------------------------------------

    @router.post("/scan")
    async def scan(request: Request, user: User = Depends(current_user), c=Depends(container)) -> dict[str, Any]:
        image = await request.body()
        if not image or len(image) > MAX_IMAGE_BYTES:
            raise HTTPException(413, "Foto mancante o troppo grande")
        try:
            read = await c.reader.read_card(image, request.headers.get("content-type", "image/jpeg"))
        except VisionError as exc:
            return {"found": False, "message": str(exc), "candidates": []}
        if not read.is_pokemon_card:
            return {"found": False, "message": "Non vedo una carta Pokémon in questa foto.", "candidates": []}
        result = await c.matcher.match(read)
        cards = []
        for cand in result.candidates:
            card = await c.catalog.get_card(cand.catalog_lang, cand.card_id)
            if card:
                cards.append(summary(card, cand.catalog_lang, card.get("set")))
        return {"found": bool(cards), "confident": result.confident, "candidates": cards,
                "read": {"name": read.name, "set_code": read.set_code, "number": read.number,
                         "language": read.language},
                "message": None if cards else "Ho letto la carta ma non la trovo nel catalogo."}

    # --- carte seguite (avvisi) -----------------------------------------------------------------------

    @router.get("/tracking")
    async def list_tracking(user: User = Depends(current_user), session: Session = Depends(db),
                            c=Depends(container)) -> dict[str, Any]:
        rows = session.query(Tracking).filter_by(user_id=user.id, active=True).order_by(Tracking.id).all()
        out = []
        for t in rows:
            card = await c.catalog.get_card(t.catalog_lang, t.card_id)  # in cache: serve solo la miniatura
            image = await card_image(c.catalog, t.catalog_lang, card) if card else None
            out.append({**_tracking_json(t), "image": image_url(image)})
        return {"trackings": out}

    @router.put("/tracking")
    async def put_tracking(body: TrackBody, user: User = Depends(current_user), session: Session = Depends(db),
                           c=Depends(container)) -> dict[str, Any]:
        langs = [x for x in body.langs if x in LANGS] or ["it"]
        quotes = await c.prices.quotes(body.card_id, body.catalog_lang, body.variant, langs, with_graded=body.psa)
        card = await c.catalog.get_card(body.catalog_lang, body.card_id)
        if card is None:
            raise HTTPException(404, "Carta non trovata")
        specs = target_specs(quotes) + (graded_specs(quotes) if body.psa else [])
        if not specs:
            raise HTTPException(422, "Per queste lingue non ci sono prezzi da seguire.")
        result = upsert_tracking(session, user, card_id=body.card_id, catalog_lang=body.catalog_lang,
                                 variant=body.variant, label=card_label(card), langs=langs, specs=specs,
                                 manage=frozenset({CARDMARKET, PSA10}))
        session.commit()
        return {"tracking": _tracking_json(result.tracking)}

    @router.delete("/tracking/{tracking_id}")
    def delete_tracking(tracking_id: int, user: User = Depends(current_user),
                        session: Session = Depends(db)) -> dict[str, Any]:
        t = session.get(Tracking, tracking_id)
        if t is None or t.user_id != user.id:
            raise HTTPException(404, "Non trovato")
        t.active = False
        session.commit()
        return {"ok": True}

    add_collection_routes(router, current_user, db, container)
    return router


def _aware(dt):
    from datetime import UTC
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _remember(session: Session, user: User, detail: dict[str, Any]) -> None:
    row = (session.query(RecentView)
           .filter_by(user_id=user.id, catalog_lang=detail["catalog_lang"], card_id=detail["id"]).one_or_none())
    if row is None:
        row = RecentView(user_id=user.id, catalog_lang=detail["catalog_lang"], card_id=detail["id"],
                         name=detail["name"])
        session.add(row)
    row.image, row.set_name, row.viewed_at = detail["image_small"], detail["set"]["name"], utcnow()
    session.flush()
    old = (session.query(RecentView).filter_by(user_id=user.id).order_by(RecentView.viewed_at.desc())
           .offset(MAX_RECENT).all())
    for r in old:
        session.delete(r)
    session.commit()


def _tracking_json(t: Tracking) -> dict[str, Any]:
    targets = [x for x in t.targets if x.active]
    return {
        "id": t.id, "card_id": t.card_id, "catalog_lang": t.catalog_lang, "variant": t.variant, "label": t.label,
        "langs": t.langs.split(","), "psa": any(x.source == PSA10 for x in targets),
        "targets": [{"source": x.source, "langs": x.langs.split(","), "baseline": x.baseline,
                     "currency": x.currency} for x in targets],
    }


def _tracking_for(session: Session, user: User, card_id: str, lang: str) -> list[dict[str, Any]]:
    rows = session.query(Tracking).filter_by(user_id=user.id, card_id=card_id, catalog_lang=lang, active=True).all()
    return [_tracking_json(t) for t in rows]

