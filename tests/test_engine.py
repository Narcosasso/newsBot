"""Flusso completo della conversazione con vision e WhatsApp finti, catalogo da fixture."""

import pytest

from cardbot.bot.engine import Engine, Incoming
from cardbot.db import ConversationState, Tracking, make_engine, make_session_factory
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

    @property
    def all(self) -> str:
        """Tutti i testi inviati dall'ultimo reset (prezzi + eventuale domanda sulle notifiche)."""
        return "\n".join(body for _, body, _ in self.sent)

    def reset(self):
        self.sent.clear()


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
    text = out.sent[-2][1]  # prezzi; l'ultimo messaggio è la domanda sulle notifiche
    assert "Charizard ex" in text and "8,13 €" in text and "Giapponese" in text
    assert out.last[0] == "buttons" and "avvisi" in out.last[1]
    assert stage(sessions) == "awaiting_notify"


async def test_asks_langs_then_remembers_them(make):
    engine, out, sessions = make(FakeVision(vr(name="Charizard ex", set_code="MEW", number="006", set_total="165")))
    await engine.handle(Incoming(WA, "image", image=b"x"))
    assert "Per quali lingue" in out.last[1] and stage(sessions) == "awaiting_langs"

    await engine.handle(Incoming(WA, "text", text="klingon"))
    assert "Non conosco «klingon»" in out.last[1]

    await engine.handle(Incoming(WA, "text", text="eng"))
    assert "TCGplayer" in out.all and stage(sessions) == "awaiting_notify"

    # Seconda foto: propone "Come l'ultima volta".
    await engine.handle(Incoming(WA, "image", image=b"x"))
    assert any(b == [("langs:last", "Come l'ultima volta")] for _, _, b in out.sent)
    await engine.handle(Incoming(WA, "button", button_id="langs:last"))
    assert "🇬🇧 Inglese" in out.all


async def test_ambiguous_photo_offers_candidates(make):
    engine, out, sessions = make(FakeVision(vr(name="Charizard ex", confidence=0.9)))
    await engine.handle(Incoming(WA, "image", image=b"x", text="ita"))
    kind, body, buttons = out.last
    assert kind == "buttons" and "Qual è la tua" in body and 1 < len(buttons) <= 3
    assert stage(sessions) == "awaiting_candidate"

    await engine.handle(Incoming(WA, "text", text="9"))
    assert "numero da 1" in out.last[1]

    await engine.handle(Incoming(WA, "button", button_id="cand:0"))
    assert stage(sessions) in {"awaiting_notify", "awaiting_variant"}


async def test_variant_is_asked_when_unclear(make):
    engine, out, sessions = make(FakeVision(vr(name="Bulbasaur", set_code="MEW", number="001", set_total="165")))
    await engine.handle(Incoming(WA, "image", image=b"x", text="ita"))
    kind, body, buttons = out.last
    assert kind == "buttons" and "Quale versione" in body
    assert [b[0] for b in buttons] == ["var:normal", "var:reverse"]
    await engine.handle(Incoming(WA, "button", button_id="var:reverse"))
    assert "Reverse holo" in out.all and "0,38 €" in out.all


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
    assert "8,13 €" in out.all and "Giapponese" in out.all and stage(sessions) == "awaiting_notify"


async def test_text_search_with_variant_word(make):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="MEW 001 reverse ita"))
    assert "Reverse holo" in out.all and "0,38 €" in out.all


async def test_text_search_restarts_a_pending_conversation(make):
    engine, out, sessions = make(FakeVision(vr(name="Charizard ex", confidence=0.9)))
    await engine.handle(Incoming(WA, "image", image=b"x"))
    assert stage(sessions) == "awaiting_candidate"
    await engine.handle(Incoming(WA, "text", text="MEW 006 eng"))
    assert "TCGplayer" in out.all and stage(sessions) == "awaiting_notify"


async def test_variant_can_be_chosen_by_number(make):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="MEW 001 ita"))
    assert "Quale versione" in out.last[1]
    await engine.handle(Incoming(WA, "text", text="2"))
    assert "Reverse holo" in out.all and "0,38 €" in out.all


async def test_text_search_not_found(make):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="ZZZ 999"))
    assert "Non trovo" in out.last[1] and "MEW 006" in out.last[1]


async def test_help(make):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="aiuto"))
    assert "Le tue carte" in out.last[1] and "stop 2" in out.last[1]


async def test_notify_yes_creates_tracking_with_shown_price_as_baseline(make):
    engine, out, sessions = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="MEW 006 ita jap kor"))
    await engine.handle(Incoming(WA, "button", button_id="notify:yes"))
    assert "Fatto!" in out.last[1] and "almeno 10% e 1,00 €" in out.last[1]
    assert "Coreano: nessun prezzo disponibile" in out.last[1]
    with sessions() as s:
        t = s.query(Tracking).one()
        assert (t.card_id, t.variant, t.langs) == ("sv03.5-006", "holo", "it,ja,ko")
        targets = {x.langs: x for x in t.targets}
        assert set(targets) == {"it", "ja"}
        assert targets["it"].id_product == 733601 and targets["it"].baseline == 8.13 and targets["it"].aggregated
        assert targets["ja"].id_product == 719448 and targets["ja"].baseline == 3.36
    assert stage(sessions) == "idle"


async def test_notify_twice_updates_instead_of_duplicating(make):
    engine, out, sessions = make(FakeVision())
    for langs in ("ita", "ita jap"):
        await engine.handle(Incoming(WA, "text", text=f"MEW 006 {langs}"))
        await engine.handle(Incoming(WA, "text", text="sì"))
    assert "Aggiornato" in out.last[1]
    with sessions() as s:
        t = s.query(Tracking).one()
        assert t.langs == "it,ja" and sorted(x.langs for x in t.targets if x.active) == ["it", "ja"]


async def test_notify_no(make):
    engine, out, sessions = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="MEW 006 ita"))
    await engine.handle(Incoming(WA, "text", text="no"))
    assert "niente avvisi" in out.last[1]
    with sessions() as s:
        assert s.query(Tracking).count() == 0


async def test_korean_only_does_not_offer_notifications(make):
    engine, out, sessions = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="MEW 006 kor"))
    assert out.last[0] == "text" and stage(sessions) == "idle"


async def _track(engine, text):
    await engine.handle(Incoming(WA, "text", text=text))
    await engine.handle(Incoming(WA, "text", text="sì"))


async def test_list_stop_and_numbering(make):
    engine, out, sessions = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="lista"))
    assert "Non segui ancora" in out.last[1]
    await _track(engine, "MEW 006 ita jap")
    await _track(engine, "MEW 001 reverse ita")
    await engine.handle(Incoming(WA, "text", text="lista"))
    listing = out.last[1]
    assert "*1. Charizard ex*" in listing and "*2. Bulbasaur*" in listing
    assert "8,13 €" in listing and "avviso a ±10% e 1,00 €" in listing

    await engine.handle(Incoming(WA, "text", text="stop 1"))
    assert "Non seguo più *Charizard ex*" in out.last[1] and "*1. Bulbasaur*" in out.last[1]
    await engine.handle(Incoming(WA, "text", text="stop 5"))
    assert "da 1 a 1" in out.last[1]
    await engine.handle(Incoming(WA, "text", text="stop tutte"))
    with sessions() as s:
        assert s.query(Tracking).filter_by(active=True).count() == 0


async def test_change_langs_keeps_existing_baseline(make):
    engine, out, sessions = make(FakeVision())
    await _track(engine, "MEW 006 ita")
    with sessions() as s:
        s.query(Tracking).one().targets[0].baseline = 7.0  # come se fosse già stato notificato
        s.commit()
    await engine.handle(Incoming(WA, "text", text="lingue 1 ita jap kor"))
    assert "ora seguo 🇮🇹 Italiano, 🇯🇵 Giapponese" in out.last[1] and "Coreano" in out.last[1]
    with sessions() as s:
        targets = {t.langs: t for t in s.query(Tracking).one().targets if t.active}
        assert targets["it"].baseline == 7.0 and targets["ja"].baseline == 3.36
    # Con una sola carta il numero si può omettere.
    await engine.handle(Incoming(WA, "text", text="lingue jap"))
    with sessions() as s:
        assert [t.langs for t in s.query(Tracking).one().targets if t.active] == ["ja"]


async def test_langs_only_untrackable_is_refused(make):
    engine, out, sessions = make(FakeVision())
    await _track(engine, "MEW 006 ita")
    await engine.handle(Incoming(WA, "text", text="lingue 1 kor"))
    assert "lascio tutto com'era" in out.last[1]
    with sessions() as s:
        assert s.query(Tracking).one().langs == "it"


async def test_thresholds_global_and_per_card(make):
    engine, out, sessions = make(FakeVision())
    await _track(engine, "MEW 006 ita")
    await _track(engine, "MEW 001 reverse ita")

    await engine.handle(Incoming(WA, "text", text="soglia 2 25%"))
    assert "25% e 1,00 €" in out.last[1]
    await engine.handle(Incoming(WA, "text", text="soglia 15% 0€"))
    assert "Ora ti avviso" in out.last[1] and "*±15%*" in out.last[1] and "1 carta ha una soglia" in out.last[1]
    await engine.handle(Incoming(WA, "text", text="lista"))
    assert "avviso a ±15%\n" in out.last[1] and "±25% e 1,00 € (solo questa carta)" in out.last[1]

    await engine.handle(Incoming(WA, "text", text="soglia 2 predefinita"))
    with sessions() as s:
        user = s.query(Tracking).first().user
        assert (user.threshold_pct, user.threshold_eur) == (15.0, None)
        assert not any(t.threshold_custom for t in s.query(Tracking).all())
    await engine.handle(Incoming(WA, "text", text="soglia"))
    assert "±15%" in out.last[1]


async def test_command_works_in_the_middle_of_a_search(make):
    engine, out, sessions = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="MEW 006"))
    assert stage(sessions) == "awaiting_langs"
    await engine.handle(Incoming(WA, "text", text="lista"))
    assert "Non segui ancora" in out.last[1]
    await engine.handle(Incoming(WA, "text", text="lingue ita, jap"))  # vale come risposta alla domanda
    assert "Giapponese" in out.all and stage(sessions) == "awaiting_notify"


async def test_welcome_on_first_message_then_the_search(make):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="MEW 006 ita"))
    assert "Ciao! Sono Cardbot" in out.sent[0][1] and "lista" in out.sent[0][1]
    assert "8,13 €" in out.all  # dopo il benvenuto esegue comunque la ricerca
    out.reset()
    await engine.handle(Incoming(WA, "text", text="MEW 006 ita"))
    assert "Ciao! Sono Cardbot" not in out.all  # il benvenuto solo la prima volta


async def test_greeting_as_first_message_gets_only_the_welcome(make):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="ciao"))
    assert len(out.sent) == 1 and "Ciao! Sono Cardbot" in out.last[1]


@pytest.mark.parametrize("text", ["/comandi", "comandi", "/aiuto", "menu", "Comandi?"])
async def test_slash_commands_show_help(make, text):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="ciao"))  # benvenuto
    await engine.handle(Incoming(WA, "text", text=text))
    assert "Cerca una carta" in out.last[1] and "novità" in out.last[1]


async def test_help_hides_photos_when_vision_is_disabled(make):
    from cardbot.recognition.vision import DisabledVision

    engine, out, _ = make(DisabledVision())
    await engine.handle(Incoming(WA, "text", text="ciao"))
    assert "foto" not in out.last[1]


async def test_news_without_cards_and_before_first_check(make):
    engine, out, _ = make(FakeVision())
    await engine.handle(Incoming(WA, "text", text="novità"))
    assert "Non segui ancora" in out.last[1]
    await _track(engine, "MEW 006 ita")
    await engine.handle(Incoming(WA, "text", text="/novita"))
    assert "Non ho ancora controllato" in out.last[1]


async def test_news_reports_moves_since_yesterday_week_and_reference(make):
    from datetime import timedelta

    from cardbot.db import PriceSnapshot, utcnow

    engine, out, sessions = make(FakeVision())
    await _track(engine, "MEW 006 ita")       # riferimento: 8,13 €
    await _track(engine, "MEW 001 reverse ita")  # nessuno snapshot: "ancora da controllare"
    now = utcnow()
    with sessions() as s:
        target = s.query(Tracking).first().targets[0]
        key = f"cm:{target.id_product}:{target.variant}:{'s' if target.shared_product else 'd'}"
        for days, trend in ((8, 7.0), (1, 8.0), (0, 9.0)):
            s.add(PriceSnapshot(series=key, source="test", source_version=f"v{days}", trend=trend,
                                fetched_at=now - timedelta(days=days)))
        s.commit()
    await engine.handle(Incoming(WA, "text", text="novità"))
    text = out.last[1]
    assert "Novità sulle tue carte" in text and "1 carta si è mossa" in text
    assert "📈 *Charizard ex*" in text and "*9,00 €*" in text
    assert "ieri +12,5%" in text and "7 gg +28,6%" in text
    assert "dal tuo riferimento (8,13 €" in text and "+10,7%" in text
    assert "Ancora da controllare: Bulbasaur" in text
