"""Server webhook: `uvicorn cardbot.app:app`."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session, sessionmaker

from cardbot.bot.engine import Engine, Incoming
from cardbot.catalog.tcgdex import TCGdexCatalog
from cardbot.config import Settings, get_settings
from cardbot.db import claim_inbound, make_engine, make_session_factory
from cardbot.prices.service import PriceService
from cardbot.recognition.matcher import CardMatcher
from cardbot.recognition.vision import CardVision
from cardbot.whatsapp.client import WhatsAppClient
from cardbot.whatsapp.webhook import InboundEvent, parse_events, verify_signature

log = logging.getLogger("cardbot")


@dataclass
class Container:
    settings: Settings
    sessions: sessionmaker[Session]
    whatsapp: WhatsAppClient
    engine: Engine


def build_container(settings: Settings) -> Container:
    sessions = make_session_factory(make_engine(settings.database_url))
    whatsapp = WhatsAppClient(settings.whatsapp_token, settings.whatsapp_phone_number_id,
                              settings.whatsapp_api_version)
    catalog = TCGdexCatalog(settings.tcgdex_base_url, settings.tcgdex_max_rps)
    engine = Engine(
        sessions, whatsapp,
        CardVision(settings.anthropic_api_key, settings.vision_model, settings.vision_effort),
        CardMatcher(catalog), PriceService(catalog), timezone=settings.timezone,
    )
    return Container(settings, sessions, whatsapp, engine)


async def process_event(c: Container, ev: InboundEvent) -> None:
    msg = Incoming(wa_id=ev.wa_id, kind=ev.kind, text=ev.text, button_id=ev.button_id)
    if ev.kind == "image" and ev.media_id:
        try:
            msg.image, msg.media_type = await c.whatsapp.download_media(ev.media_id)
        except Exception:
            log.exception("Download della foto fallito")
            await c.whatsapp.send_text(ev.wa_id, "⚠️ Non riesco a scaricare la foto, riprova.")
            return
    await c.engine.handle(msg)


def create_app(container: Container | None = None) -> FastAPI:
    app = FastAPI(title="cardbot")
    state: dict[str, Container] = {}

    def get() -> Container:
        if "c" not in state:
            state["c"] = container or build_container(get_settings())
        return state["c"]

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/webhook")
    async def verify(mode: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"),
                     challenge: str = Query("", alias="hub.challenge")) -> Response:
        expected = get().settings.whatsapp_verify_token
        if mode == "subscribe" and expected and token == expected:
            return Response(content=challenge, media_type="text/plain")
        raise HTTPException(status_code=403, detail="verify token errato")

    @app.post("/webhook")
    async def receive(request: Request, background: BackgroundTasks) -> dict[str, str]:
        c = get()
        body = await request.body()
        if not verify_signature(c.settings.whatsapp_app_secret, body, request.headers.get("X-Hub-Signature-256")):
            raise HTTPException(status_code=403, detail="firma non valida")
        allowed = c.settings.allowed_wa_id_set
        for ev in parse_events(await request.json()):
            if allowed and ev.wa_id not in allowed:
                log.info("Messaggio ignorato da numero non autorizzato")
                continue
            if ev.kind == "other":
                continue
            if not claim_inbound(c.sessions, ev.message_id, ev.wa_id):
                continue  # già ricevuto: Meta ha ritentato il webhook
            background.add_task(process_event, c, ev)
        # Rispondiamo subito 200: l'elaborazione (foto, riconoscimento, prezzi) avviene dopo.
        return {"status": "ok"}

    return app


app = create_app()
