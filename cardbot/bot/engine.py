"""Flusso della conversazione: foto -> riconoscimento -> (conferma carta/variante) -> lingue -> prezzi."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from cardbot.bot.format import HELP, format_quotes
from cardbot.db import get_or_create_user, load_state, save_state
from cardbot.langs import format_langs, parse_langs, supported_help
from cardbot.prices.service import PriceService
from cardbot.recognition.matcher import Candidate, CardMatcher
from cardbot.recognition.vision import CardVision, VisionError
from cardbot.variants import LABELS_IT, choose_variant

log = logging.getLogger(__name__)

BAD_PHOTO_TIPS = ("Prova con una foto più nitida: carta dritta, ben illuminata, senza riflessi, "
                  "con nome e numero in basso leggibili.")


@dataclass
class Incoming:
    wa_id: str
    kind: str  # "text" | "image" | "button"
    text: str | None = None
    button_id: str | None = None
    image: bytes | None = None
    media_type: str = "image/jpeg"


class Messenger(Protocol):
    async def send_text(self, to: str, text: str) -> None: ...

    async def send_buttons(self, to: str, body: str, buttons: list[tuple[str, str]]) -> None: ...


class Engine:
    def __init__(self, session_factory: sessionmaker[Session], messenger: Messenger, vision: CardVision,
                 matcher: CardMatcher, prices: PriceService, timezone: str = "Europe/Rome") -> None:
        self._sessions = session_factory
        self._out = messenger
        self._vision = vision
        self._matcher = matcher
        self._prices = prices
        self._tz = timezone

    async def handle(self, msg: Incoming) -> None:
        with self._sessions() as session:
            user = get_or_create_user(session, msg.wa_id)
            state = load_state(session, user)
            try:
                await self._dispatch(session, user, state, msg)
            except Exception:
                log.exception("Errore gestendo il messaggio di %s", msg.wa_id)
                save_state(state, "idle")
                await self._out.send_text(msg.wa_id, "😵 Qualcosa è andato storto. Riprova tra poco.")
            session.commit()

    # --- smistamento -------------------------------------------------------------------------------

    async def _dispatch(self, session, user, state, msg: Incoming) -> None:
        if msg.kind == "image" and msg.image:
            await self._on_image(user, state, msg)
            return
        reply = (msg.button_id or msg.text or "").strip()
        lowered = reply.lower()
        if lowered in {"annulla", "reset"}:
            save_state(state, "idle")
            await self._out.send_text(user.wa_id, "Ok, annullato. Mandami una foto quando vuoi.")
            return
        if state.stage == "awaiting_candidate":
            await self._on_candidate_reply(user, state, lowered)
        elif state.stage == "awaiting_variant":
            await self._on_variant_reply(user, state, lowered)
        elif state.stage == "awaiting_langs":
            await self._on_langs_reply(user, state, reply)
        elif lowered in {"aiuto", "help", "?", "ciao", "start"}:
            await self._out.send_text(user.wa_id, HELP)
        elif lowered == "lingue":
            await self._out.send_text(user.wa_id, f"Lingue supportate: {supported_help()}")
        else:
            await self._out.send_text(user.wa_id, "Mandami la foto di una carta Pokémon 📸 (scrivi *aiuto* "
                                                  "per i comandi).")

    # --- foto ----------------------------------------------------------------------------------------

    async def _on_image(self, user, state, msg: Incoming) -> None:
        await self._out.send_text(user.wa_id, "🔍 Analizzo la foto…")
        try:
            vision = await self._vision.read_card(msg.image, msg.media_type)
        except VisionError as exc:
            await self._out.send_text(user.wa_id, f"⚠️ {exc}.")
            return
        if not vision.is_pokemon_card:
            await self._out.send_text(user.wa_id, "Non mi sembra una carta Pokémon. " + BAD_PHOTO_TIPS)
            return

        result = await self._matcher.match(vision)
        if not result.candidates:
            read = ", ".join(x for x in (vision.name, vision.set_code, vision.number) if x) or "nulla"
            await self._out.send_text(user.wa_id, f"Ho letto: _{read}_, ma non trovo la carta nel catalogo. "
                                                  + BAD_PHOTO_TIPS)
            return

        payload = {
            "candidates": [asdict(c) for c in result.candidates],
            "hint": vision.variant_hint,
            "warnings": result.warnings,
            "langs": parse_langs(msg.text).langs if msg.text and parse_langs(msg.text).ok else None,
        }
        if result.confident:
            payload["selected"] = payload["candidates"][0]
            await self._after_card(user, state, payload)
            return

        save_state(state, "awaiting_candidate", payload)
        lines = ["🤔 Non sono sicuro al 100%. Quale di queste è?"]
        for i, c in enumerate(result.candidates, 1):
            lines.append(f"{i}) {c.short()}")
        lines.append("Se nessuna è giusta, rimanda una foto più nitida.")
        buttons = [(f"cand:{i}", str(i + 1)) for i in range(len(result.candidates))]
        await self._out.send_buttons(user.wa_id, "\n".join(lines), buttons)

    async def _on_candidate_reply(self, user, state, reply: str) -> None:
        payload = dict(state.payload)
        cands = payload.get("candidates") or []
        idx = None
        if reply.startswith("cand:"):
            idx = int(reply.split(":", 1)[1])
        elif reply.isdigit():
            idx = int(reply) - 1
        if idx is None or not 0 <= idx < len(cands):
            await self._out.send_text(user.wa_id, f"Rispondi con un numero da 1 a {len(cands)}, "
                                                  "oppure *annulla*.")
            return
        payload["selected"] = cands[idx]
        await self._after_card(user, state, payload)

    # --- variante e lingue -------------------------------------------------------------------------

    async def _after_card(self, user, state, payload: dict) -> None:
        cand = Candidate(**payload["selected"])
        variant = payload.get("variant") or choose_variant(cand.variants, payload.get("hint", "unknown"))
        if variant is None:
            save_state(state, "awaiting_variant", payload)
            buttons = [(f"var:{v}", LABELS_IT[v]) for v in cand.variants[:3]]
            await self._out.send_buttons(user.wa_id, f"*{cand.short()}*\nQuale versione hai?", buttons)
            return
        payload["variant"] = variant
        langs = payload.get("langs")
        if langs:
            await self._send_prices(user, state, payload, langs)
            return
        save_state(state, "awaiting_langs", payload)
        body = (f"✅ *{cand.short()}* · {LABELS_IT[variant]}\n\nQuali lingue ti interessano? "
                "Es. *ita, eng, jap*")
        if user.langs:
            last = format_langs(user.langs.split(","))
            await self._out.send_buttons(user.wa_id, body, [("langs:last", "Come l'ultima volta")])
            await self._out.send_text(user.wa_id, f"_(ultima volta: {last})_")
        else:
            await self._out.send_text(user.wa_id, body)

    async def _on_variant_reply(self, user, state, reply: str) -> None:
        payload = dict(state.payload)
        cand = Candidate(**payload["selected"])
        mapping = {"normale": "normal", "normal": "normal", "holo": "holo", "reverse": "reverse",
                   "reverse holo": "reverse"}
        variant = reply.split(":", 1)[1] if reply.startswith("var:") else mapping.get(reply)
        if variant not in cand.variants:
            options = ", ".join(LABELS_IT[v].lower() for v in cand.variants)
            await self._out.send_text(user.wa_id, f"Scegli una versione tra: {options}.")
            return
        payload["variant"] = variant
        await self._after_card(user, state, payload)

    async def _on_langs_reply(self, user, state, reply: str) -> None:
        payload = dict(state.payload)
        if reply == "langs:last" and user.langs:
            langs = user.langs.split(",")
        else:
            parsed = parse_langs(reply)
            if not parsed.ok:
                unknown = f" Non conosco: {', '.join(parsed.unknown)}." if parsed.unknown else ""
                await self._out.send_text(user.wa_id, f"Non ho capito le lingue.{unknown} "
                                                      f"Usa per esempio: ita, eng, jap ({supported_help()}).")
                return
            langs = parsed.langs
        await self._send_prices(user, state, payload, langs)

    async def _send_prices(self, user, state, payload: dict, langs: list[str]) -> None:
        cand = Candidate(**payload["selected"])
        variant = payload["variant"]
        quotes = await self._prices.quotes(cand.card_id, cand.catalog_lang, variant, langs)
        text = format_quotes(cand.short(), variant, quotes, tz=self._tz, warnings=payload.get("warnings"))
        await self._out.send_text(user.wa_id, text)
        user.langs = ",".join(langs)
        save_state(state, "idle", {"last_card": payload["selected"], "variant": variant, "langs": langs})
