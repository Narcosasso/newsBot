"""Prezzi PSA 10 (PokemonPriceTracker): client, servizio prezzi, chat, job giornaliero."""

import json
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
import respx

from cardbot.alerts.sources import PriceData
from cardbot.bot.engine import Engine, Incoming
from cardbot.db import Notification, Tracking, TrackingTarget, User, make_engine, make_session_factory, utcnow
from cardbot.jobs.poll import run_poll
from cardbot.prices.graded import BASE_URL, GradedPrices, GradedQuote, quote_from_card
from cardbot.prices.service import PriceService
from cardbot.recognition.matcher import CardMatcher
from tests.test_engine import FakeMessenger, FakeVision

FIX = Path(__file__).parent / "fixtures" / "ppt"
WA = "393330000000"


def fixture(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def card(name: str) -> dict:
    data = fixture(name)["data"]
    return data[0] if isinstance(data, list) else data


# --- lettura della risposta ----------------------------------------------------------------------------------

def test_quote_from_real_responses():
    g = quote_from_card(card("gengar_30th_search"), "english")
    assert (g.card_name, g.tcgplayer_id, g.price, g.median, g.sales, g.trend) == \
        ("Gengar ex", "717610", 555.0, 630.0, 64, "down")
    assert g.has_sales and g.confidence == "high" and g.currency == "USD" and g.updated is not None
    c = quote_from_card(card("charizard_151_by_id"), "english")
    assert c.price == 50.14 and c.sales == 89 and c.trend == "up"
    jp = quote_from_card(card("gengar_m6a_japanese"), "japanese")
    assert not jp.has_sales and jp.price is None  # nessuna vendita PSA 10 per la giapponese


# --- client ---------------------------------------------------------------------------------------------------

def _resp(name: str, remaining: int = 90, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=fixture(name), headers={"X-Ratelimit-Daily-Remaining": str(remaining)})


@respx.mock
async def test_by_id_asks_for_one_card_with_graded_sales_and_caches():
    route = respx.get(f"{BASE_URL}/cards").mock(return_value=_resp("charizard_151_by_id", remaining=77))
    client = GradedPrices("k")
    q = await client.by_id("502558")
    assert q.price == 50.14 and client.remaining == 77
    params = route.calls.last.request.url.params
    assert params["tcgPlayerId"] == "502558" and params["limit"] == "1" and params["includeEbay"] == "true"
    assert route.calls.last.request.headers["Authorization"] == "Bearer k"
    await client.by_id("502558")
    assert route.call_count == 1  # seconda volta dalla cache: nessun credito


@respx.mock
async def test_search_accepts_only_the_same_card_number():
    route = respx.get(f"{BASE_URL}/cards").mock(return_value=_resp("gengar_30th_search"))
    client = GradedPrices("k")
    assert (await client.search("Gengar ex", "154", "128")).tcgplayer_id == "717610"
    assert route.calls.last.request.url.params["search"] == "Gengar ex 154/128"
    assert await client.search("Gengar ex", "155", "128") is None  # risultato con un altro numero: scartato
    await client.by_id("717610")
    assert route.call_count == 2  # l'ID trovato con la ricerca è già in cache


@respx.mock
async def test_chat_lookups_stop_before_eating_the_job_reserve():
    respx.get(f"{BASE_URL}/cards").mock(return_value=_resp("charizard_151_by_id", remaining=15))
    client = GradedPrices("k")
    await client.by_id("502558")  # aggiorna i crediti rimasti: 15
    assert await client.by_id("999", for_chat=True) is None
    assert respx.calls.call_count == 1
    assert await client.by_id("999") is not None  # il job può ancora usarli


@respx.mock
async def test_out_of_credits_returns_nothing():
    respx.get(f"{BASE_URL}/cards").mock(return_value=httpx.Response(429, json={"error": "limit"}))
    assert await GradedPrices("k").by_id("1") is None


# --- servizio prezzi e chat -------------------------------------------------------------------------------------

class FakeGraded:
    enabled = True

    def __init__(self, price: float | None = 50.14, sales: int = 89):
        self.price, self.sales = price, sales
        self.calls: list = []

    def _quote(self, tid: str, language: str) -> GradedQuote:
        return GradedQuote(grade="psa10", tcgplayer_id=tid, card_name="Charizard ex", set_name="151",
                           language=language, price=self.price, confidence="high", median=90.0, sales=self.sales,
                           trend="up", updated=utcnow())

    async def by_id(self, tid, language="english", for_chat=False):
        self.calls.append(("id", tid, language))
        return self._quote(tid, language)

    async def search(self, name, number, total, language="english", for_chat=False):
        self.calls.append(("search", name, number, total, language))
        return self._quote("777", language)


async def test_service_uses_the_tcgplayer_id_from_the_catalog(catalog):
    graded = FakeGraded()
    quotes = await PriceService(catalog, graded=graded).quotes("sv03.5-006", "en", "holo", ["it"])
    assert quotes[0].graded.price == 50.14
    assert graded.calls == [("id", "502558", "english")]


async def test_service_without_key_has_no_graded(catalog):
    quotes = await PriceService(catalog).quotes("sv03.5-006", "en", "holo", ["it"])
    assert quotes[0].graded is None


@pytest.fixture
def bot(catalog):
    def _make(graded):
        sessions = make_session_factory(make_engine("sqlite://"))
        out = FakeMessenger()
        engine = Engine(sessions, out, FakeVision(), CardMatcher(catalog), PriceService(catalog, graded=graded))
        return engine, out, sessions
    return _make


async def test_price_message_and_buttons_offer_psa10(bot):
    engine, out, sessions = bot(FakeGraded())
    await engine.handle(Incoming(WA, "text", text="MEW 006 ita"))
    assert "🏅 PSA 10: *50,14 $* · mediana 90,00 $ · 89 vendite 📈" in out.all
    assert "vendite eBay e Fanatics negli USA" in out.all
    assert [b[0] for b in out.last[2]] == ["notify:yes", "notify:psa", "notify:no"]

    await engine.handle(Incoming(WA, "button", button_id="notify:psa"))
    assert "Seguo anche il prezzo *PSA 10*" in out.last[1]
    with sessions() as s:
        targets = {t.source: t for t in s.query(TrackingTarget).all()}
        assert set(targets) == {"cardmarket", "psa10"}
        psa = targets["psa10"]
        assert (psa.external_id, psa.currency, psa.baseline, psa.id_product) == ("502558", "USD", 50.14, None)

    await engine.handle(Incoming(WA, "text", text="lista"))
    assert "🏅 PSA 10 50,14 $" in out.last[1] and "🇮🇹 8,13 €" in out.last[1]


async def test_plain_yes_does_not_track_psa10(bot):
    engine, out, sessions = bot(FakeGraded())
    await engine.handle(Incoming(WA, "text", text="MEW 006 ita"))
    await engine.handle(Incoming(WA, "button", button_id="notify:yes"))
    with sessions() as s:
        assert [t.source for t in s.query(TrackingTarget).all()] == ["cardmarket"]


async def test_psa_command_adds_and_removes_without_touching_languages(bot):
    engine, out, sessions = bot(FakeGraded())
    await engine.handle(Incoming(WA, "text", text="MEW 006 ita jap"))
    await engine.handle(Incoming(WA, "text", text="sì"))
    await engine.handle(Incoming(WA, "text", text="psa 1"))
    assert "Seguo anche il prezzo PSA 10" in out.last[1] and "1,00 $" in out.last[1]
    with sessions() as s:
        active = sorted((t.source, t.langs) for t in s.query(TrackingTarget).filter_by(active=True))
        assert ("psa10", "en") in active and ("cardmarket", "it") in active and ("cardmarket", "ja") in active
    await engine.handle(Incoming(WA, "text", text="psa 1 stop"))
    assert "Non seguo più il prezzo PSA 10" in out.last[1]
    with sessions() as s:
        assert {t.source for t in s.query(TrackingTarget).filter_by(active=True)} == {"cardmarket"}


async def test_psa_command_when_there_are_no_sales_or_no_key(bot, catalog):
    engine, out, _ = bot(FakeGraded(price=None, sales=0))
    await _track_plain(engine)
    await engine.handle(Incoming(WA, "text", text="psa"))
    assert "non ha ancora vendite PSA 10" in out.last[1]
    engine, out, _ = bot(None)
    await _track_plain(engine)
    await engine.handle(Incoming(WA, "text", text="psa 1"))
    assert "non sono attivi" in out.last[1]


async def _track_plain(engine):
    await engine.handle(Incoming(WA, "text", text="MEW 006 ita"))
    await engine.handle(Incoming(WA, "text", text="sì"))


# --- job giornaliero ---------------------------------------------------------------------------------------------

class NoChangeGuide:
    name = "cardmarket_price_guide"

    async def fetch(self, etag=None):
        return None  # 304: il price guide non è cambiato


class Sender:
    def __init__(self):
        self.texts = []

    async def send_text(self, to, text):
        self.texts.append(text)
        return "wamid"

    async def send_template(self, to, name, lang, params):
        self.texts.append(" ".join(params))
        return "wamid"


@pytest.fixture
def db_with_psa():
    sessions = make_session_factory(make_engine("sqlite://"))
    with sessions() as s:
        user = User(wa_id=WA, last_inbound_at=utcnow())
        s.add(user)
        s.flush()
        tr = Tracking(user_id=user.id, card_id="30th-154", catalog_lang="en", variant="holo",
                      label="Gengar ex · 30th Celebration 154/128", langs="it")
        s.add(tr)
        s.flush()
        tr.targets.append(TrackingTarget(source="psa10", langs="it", card_id="30th-154", catalog_lang="en",
                                         id_product=None, external_id="717610", currency="USD", variant="holo",
                                         baseline=480.0, baseline_at=utcnow() - timedelta(days=3), active=True))
        s.commit()
    return sessions


async def test_job_checks_psa10_even_when_cardmarket_is_unchanged(db_with_psa):
    class Graded:
        enabled = True

        async def by_id(self, tid, language="english", for_chat=False):
            return quote_from_card(card("gengar_30th_search"), language)  # 555 $

    sender = Sender()
    report = await run_poll(db_with_psa, NoChangeGuide(), sender, "price_alert", "it", graded=Graded())
    assert report.status == "invariato (304)" and report.evaluation.graded_checked == 1
    assert len(sender.texts) == 1 and "🏅 PSA 10 480,00 $ → 555,00 $ (+15,6%)" in sender.texts[0]
    # Stesso aggiornamento il giorno dopo: nessun doppione.
    await run_poll(db_with_psa, NoChangeGuide(), sender, "price_alert", "it", graded=Graded())
    with db_with_psa() as s:
        assert s.query(Notification).count() == 1
        assert s.query(TrackingTarget).one().baseline == 555.0


async def test_news_shows_psa10_in_dollars(db_with_psa):
    from cardbot.alerts.news import build_news

    class Graded:
        enabled = True

        async def by_id(self, tid, language="english", for_chat=False):
            return quote_from_card(card("gengar_30th_search"), language)

    await run_poll(db_with_psa, NoChangeGuide(), None, "price_alert", "it", graded=Graded())
    with db_with_psa() as s:
        text = build_news(s, s.query(User).one())
    assert "🏅 PSA 10 *555,00 $*" in text


def test_cardmarket_only_job_still_works_without_graded():
    data = PriceData(source="cardmarket_price_guide", version="v1", entries={})
    assert data.entries == {}
