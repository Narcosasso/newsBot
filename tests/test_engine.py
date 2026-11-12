"""Flusso completo della conversazione con vision e WhatsApp finti, catalogo da fixture."""

import pytest

from cardbot.bot.engine import Engine, Incoming
from cardbot.db import ConversationState, make_engine, make_session_factory
from cardbot.prices.service import PriceService
from cardbot.recognition.matcher import CardMatcher
from cardbot.recognition.vision import VisionError, VisionResult

WA = "393330000000"


class FakeMessenger:
    def __init__(self):
        self.sent: list[tuple[str, str, list]] = []

    async def send_text(self, to, text):
        self.sent.append(("text", text, []))

    async def send_buttons(self, to, body, buttons):
        self.sent.append(("buttons", body, buttons))

    @property
    def last(self):
        return self.sent[-1]


class FakeVision:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    async def read_card(self, image, media_type="image/jpeg"):
        if self.error:
            raise self.error
        return self.result


def vr(**kw):
    base = dict(is_pokemon_card=True, language="en", confidence=0.95)
    base.update(kw)
    return VisionResult(**base)


@pytest.fixture
def make(catalog):
    def _make(vision):
        sessions = make_session_factory(make_engine("sqlite://"))
        out = FakeMessenger()
        engine = Engine(sessions, out, vision, CardMatcher(catalog), PriceService(catalog))
        return engine, out, sessions
    return _make


def stage(sessions):
    with sessions() as s:
        st = s.get(ConversationState, 1)
        return st.stage if st else None


async def test_confident_photo_with_caption_langs_replies_prices(make):
    engine, out, sessions = make(FakeVision(vr(name="Charizard ex", set_code="MEW", number="006", set_total="165",
                                               variant_hint="holo")))
    await engine.handle(Incoming(WA, "image", image=b"x", text="ita, jap"))
    kind, text, _ = out.last
    assert kind == "text" and "Charizard ex" in text and "8,13 €" in text and "JAP" in text
    assert stage(sessions) == "idle"


async def test_asks_langs_then_remembers_them(make):
    engine, out, sessions = make(FakeVision(vr(name="Charizard ex", set_code="MEW", number="006", set_total="165")))
    await engine.handle(Incoming(WA, "image", image=b"x"))
    assert "Quali lingue" in out.last[1] and stage(sessions) == "awaiting_langs"

    await engine.handle(Incoming(WA, "text", text="klingon"))
    assert "Non ho capito" in out.last[1]

    await engine.handle(Incoming(WA, "text", text="eng"))
    assert "TCGplayer" in out.last[1] and stage(sessions) == "idle"

    # Seconda foto: propone "Come l'ultima volta".
    await engine.handle(Incoming(WA, "image", image=b"x"))
    assert any(b == [("langs:last", "Come l'ultima volta")] for _, _, b in out.sent)
    await engine.handle(Incoming(WA, "button", button_id="langs:last"))
    assert "🇬🇧 ENG" in out.last[1]


async def test_ambiguous_photo_offers_candidates(make):
    engine, out, sessions = make(FakeVision(vr(name="Charizard ex", confidence=0.9)))
    await engine.handle(Incoming(WA, "image", image=b"x", text="ita"))
    kind, body, buttons = out.last
    assert kind == "buttons" and "Quale di queste" in body and 1 < len(buttons) <= 3
    assert stage(sessions) == "awaiting_candidate"

    await engine.handle(Incoming(WA, "text", text="9"))
    assert "numero da 1" in out.last[1]

    await engine.handle(Incoming(WA, "button", button_id="cand:0"))
    assert stage(sessions) in {"idle", "awaiting_variant"}


async def test_variant_is_asked_when_unclear(make):
    engine, out, sessions = make(FakeVision(vr(name="Bulbasaur", set_code="MEW", number="001", set_total="165")))
    await engine.handle(Incoming(WA, "image", image=b"x", text="ita"))
    kind, body, buttons = out.last
    assert kind == "buttons" and "Quale versione" in body
    assert [b[0] for b in buttons] == ["var:normal", "var:reverse"]
    await engine.handle(Incoming(WA, "button", button_id="var:reverse"))
    assert "Reverse holo" in out.last[1] and "0,38 €" in out.last[1]


async def test_not_a_card(make):
    engine, out, _ = make(FakeVision(vr(is_pokemon_card=False, language="other")))
    await engine.handle(Incoming(WA, "image", image=b"x"))
    assert "Non mi sembra una carta" in out.last[1]


async def test_vision_error_is_reported(make):
    engine, out, _ = make(FakeVision(error=VisionError("Servizio di riconoscimento non raggiungibile")))
    await engine.handle(Incoming(WA, "image", image=b"x"))
    assert "non raggiungibile" in out.last[1]


async def test_cancel_resets_state(make):
    engine, out, sessions = make(FakeVision(vr(name="Charizard ex", set_code="MEW", number="006", set_total="165")))
    await engine.handle(Incoming(WA, "image", image=b"x"))
    await engine.handle(Incoming(WA, "text", text="annulla"))
    assert stage(sessions) == "idle"


async def test_text_search_with_langs_replies_prices_without_vision(make):
    engine, out, sessions = make(FakeVision(error=AssertionError("la vision non va usata")))
    await engine.handle(Incoming(WA, "text", text="MEW 006 ita jap"))
    assert "8,13 €" in out.last[1] and "JAP" in out.last[1] and stage(sessions) == "idle"


async def test_text_search_with_variant_word(make):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="MEW 001 reverse ita"))
    assert "Reverse holo" in out.last[1] and "0,38 €" in out.last[1]


async def test_text_search_restarts_a_pending_conversation(make):
    engine, out, sessions = make(FakeVision(vr(name="Charizard ex", confidence=0.9)))
    await engine.handle(Incoming(WA, "image", image=b"x"))
    assert stage(sessions) == "awaiting_candidate"
    await engine.handle(Incoming(WA, "text", text="MEW 006 eng"))
    assert "TCGplayer" in out.last[1] and stage(sessions) == "idle"


async def test_variant_can_be_chosen_by_number(make):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="MEW 001 ita"))
    assert "Quale versione" in out.last[1]
    await engine.handle(Incoming(WA, "text", text="2"))
    assert "Reverse holo" in out.last[1] and "0,38 €" in out.last[1]


async def test_text_search_not_found(make):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="ZZZ 999"))
    assert "Non trovo" in out.last[1] and "MEW 006" in out.last[1]


async def test_help(make):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="aiuto"))
    assert "Comandi" in out.last[1]
