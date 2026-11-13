"""Strumenti locali, senza WhatsApp.

  python -m cardbot.cli simulate foto.jpg --langs ita,eng   # flusso completo (serve ANTHROPIC_API_KEY)
  python -m cardbot.cli search "MEW 006 ita jap"            # ricerca testuale, nessuna chiave
  python -m cardbot.cli prices sv03.5-006 --variant holo --langs ita,eng,jap   # solo prezzi, nessuna chiave
"""

from __future__ import annotations

import argparse
import asyncio
import mimetypes
import sys
from pathlib import Path

from cardbot.bot.engine import Engine, Incoming
from cardbot.bot.format import format_quotes
from cardbot.catalog.tcgdex import TCGdexCatalog
from cardbot.config import get_settings
from cardbot.db import ConversationState, make_engine, make_session_factory
from cardbot.langs import parse_langs
from cardbot.prices.service import PriceService
from cardbot.recognition.matcher import CardMatcher
from cardbot.recognition.readers import make_reader
from cardbot.recognition.vision import VisionError

CLI_USER = "cli-user"


class ConsoleMessenger:
    async def send_text(self, to: str, text: str) -> None:
        print(f"\n🤖 {text}\n")

    async def send_buttons(self, to: str, body: str, buttons: list[tuple[str, str]]) -> None:
        print(f"\n🤖 {body}")
        for bid, title in buttons:
            print(f"   [{title}]  (rispondi: {bid})")
        print()


class NoVision:
    async def read_card(self, image: bytes, media_type: str = "image/jpeg"):
        raise VisionError("Riconoscimento foto non disponibile in questa modalità")


async def simulate(image_path: Path, langs: str | None) -> int:
    settings = get_settings()
    vision = make_reader(settings)
    if not vision.enabled:
        print("Foto disattivate: imposta PHOTO_READER=google (con GOOGLE_VISION_API_KEY in locale) "
              "oppure PHOTO_READER=claude con ANTHROPIC_API_KEY.", file=sys.stderr)
        return 2
    media_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
    return await _converse(vision, Incoming(wa_id=CLI_USER, kind="image", image=image_path.read_bytes(),
                                            media_type=media_type, text=langs))


async def search(text: str) -> int:
    return await _converse(NoVision(), Incoming(wa_id=CLI_USER, kind="text", text=text))


async def _converse(vision, first: Incoming) -> int:
    settings = get_settings()
    sessions = make_session_factory(make_engine("sqlite://"))
    catalog = TCGdexCatalog(settings.tcgdex_base_url, settings.tcgdex_max_rps)
    from cardbot.app import _graded

    engine = Engine(sessions, ConsoleMessenger(), vision, CardMatcher(catalog),
                    PriceService(catalog, graded=_graded(settings)),
                    timezone=settings.timezone)
    print(f"tu> {first.text or '[foto]'}")
    await engine.handle(first)
    while True:
        with sessions() as s:
            stage = (s.get(ConversationState, 1) or ConversationState(stage="idle")).stage
        if stage == "idle":
            break
        try:
            reply = input("tu> ").strip()
        except EOFError:
            break
        await engine.handle(Incoming(wa_id=CLI_USER, kind="text", text=reply))
    await catalog.aclose()
    return 0


async def prices(card_id: str, catalog_lang: str, variant: str, langs: str) -> int:
    parsed = parse_langs(langs)
    if not parsed.ok:
        print(f"Lingue non valide: {parsed.unknown}", file=sys.stderr)
        return 2
    catalog = TCGdexCatalog(get_settings().tcgdex_base_url)
    try:
        quotes = await PriceService(catalog).quotes(card_id, catalog_lang, variant, parsed.langs)
        card = await catalog.get_card(catalog_lang, card_id) or {}
    finally:
        await catalog.aclose()
    title = f"{card.get('name', card_id)} · {(card.get('set') or {}).get('name', '')} {card.get('localId', '')}"
    print(format_quotes(title, variant, quotes))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cardbot")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_sim = sub.add_parser("simulate", help="simula una conversazione partendo da una foto")
    p_sim.add_argument("image", type=Path)
    p_sim.add_argument("--langs", help="lingue, es. 'ita,eng,jap' (altrimenti te le chiede)")
    p_se = sub.add_parser("search", help="simula una ricerca testuale, es. 'MEW 006 ita jap' (nessuna chiave)")
    p_se.add_argument("text")
    p_pr = sub.add_parser("prices", help="prezzi di una carta TCGdex per lingua")
    p_pr.add_argument("card_id", help="id TCGdex, es. sv03.5-006 o SV2a-006")
    p_pr.add_argument("--catalog", default="en", help="catalogo TCGdex della carta (en, it, ja, …)")
    p_pr.add_argument("--variant", default="normal", choices=["normal", "holo", "reverse"])
    p_pr.add_argument("--langs", default="ita,eng,jap")
    args = parser.parse_args(argv)
    if args.cmd == "simulate":
        return asyncio.run(simulate(args.image, args.langs))
    if args.cmd == "search":
        return asyncio.run(search(args.text))
    return asyncio.run(prices(args.card_id, args.catalog, args.variant, args.langs))


if __name__ == "__main__":
    raise SystemExit(main())
