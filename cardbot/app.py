"""Server webhook: `uvicorn cardbot.app:app`."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from cardbot.bot.engine import Engine, Incoming
from cardbot.catalog.tcgdex import TCGdexCatalog
from cardbot.config import Settings, get_settings
from cardbot.db import claim_inbound, make_engine, make_session_factory
from cardbot.prices.fx import FxRates
from cardbot.prices.service import PriceService
from cardbot.push import PushSender
from cardbot.recognition.matcher import CardMatcher
from cardbot.recognition.quota import QuotaReader
from cardbot.recognition.readers import make_reader
from cardbot.whatsapp.client import WhatsAppClient
from cardbot.whatsapp.webhook import InboundEvent, parse_events, verify_signature

log = logging.getLogger("cardbot")
# Su Cloud Run si legge solo ciò che finisce sullo standard output: mostriamo anche i messaggi INFO del bot.
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@dataclass
class Container:
    settings: Settings
    sessions: sessionmaker[Session]
    whatsapp: WhatsAppClient
    engine: Engine
    # Usati dall'app PokeVault (stessi oggetti del bot: cache e crediti condivisi).
    catalog: Any = None
    prices: Any = None
    matcher: Any = None
    reader: Any = None
    fx: Any = None
    push: Any = None  # PushSender (notifiche dell'app)


def _graded(settings: Settings):
    if not settings.pokemonpricetracker_api_key:
        return None
    from cardbot.prices.graded import GradedPrices
    return GradedPrices(settings.pokemonpricetracker_api_key)


def build_container(settings: Settings) -> Container:
    sessions = make_session_factory(make_engine(settings.database_url))
    whatsapp = WhatsAppClient(settings.whatsapp_token, settings.whatsapp_phone_number_id,
                              settings.whatsapp_api_version)
    catalog = TCGdexCatalog(settings.tcgdex_base_url, settings.tcgdex_max_rps)
    reader, matcher = make_reader(settings), CardMatcher(catalog)
    if settings.photo_reader.strip().lower() in ("", "google"):
        reader = QuotaReader(reader, sessions, settings.vision_monthly_limit)
    prices = PriceService(catalog, graded=_graded(settings))
    engine = Engine(sessions, whatsapp, reader, matcher, prices, timezone=settings.timezone)
    return Container(settings, sessions, whatsapp, engine, catalog=catalog, prices=prices, matcher=matcher,
                     reader=reader, fx=FxRates(),
                     push=PushSender(sessions, settings.vapid_subject, settings.vapid_public_key,
                                     settings.vapid_private_key))


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

    # Su Cloud Run i percorsi che finiscono con "z" (es. /healthz) sono riservati da Google: si usa /health.
    @app.get("/health")
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
                log.warning("Messaggio ignorato: il mittente non è in ALLOWED_WA_IDS")
                continue
            if ev.kind == "other":
                continue
            if not claim_inbound(c.sessions, ev.message_id, ev.wa_id):
                continue  # già ricevuto: Meta ha ritentato il webhook
            background.add_task(process_event, c, ev)
        # Rispondiamo subito 200: l'elaborazione (foto, riconoscimento, prezzi) avviene dopo.
        return {"status": "ok"}

    # App PokeVault: API e interfaccia (la cartella web/dist si crea con "npm run build" in web/).
    from cardbot.web.api import build_api
    app.include_router(build_api(get))

    @app.exception_handler(httpx.HTTPError)
    async def upstream_down(request: Request, exc: httpx.HTTPError):
        # Una fonte esterna (catalogo, prezzi) non risponde: messaggio chiaro invece di "Errore 500".
        log.warning("Fonte esterna non disponibile per %s: %s", request.url.path, exc)
        return JSONResponse({"detail": "Il catalogo delle carte non risponde in questo momento: riprova tra "
                                       "qualche secondo."}, status_code=503)
    dist = Path((container.settings if container else get_settings()).web_dist)
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")

    return app


app = create_app()
