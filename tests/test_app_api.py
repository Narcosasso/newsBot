"""API dell'app PokeVault: accesso con PIN, ricerca, scheda carta, gradate, recenti, scansione, carte seguite."""

import pytest
from fastapi.testclient import TestClient

from cardbot.app import Container, create_app
from cardbot.config import Settings
from cardbot.db import AppSession, TrackingTarget, make_engine, make_session_factory
from cardbot.prices.service import PriceService
from cardbot.push import PushSender
from cardbot.recognition.matcher import CardMatcher
from cardbot.recognition.ocr import parse_card_text
from cardbot.recognition.vision import VisionError
from tests.test_graded import FakeGraded
from tests.test_ocr import CHARIZARD_IT

PIN = "482915"


class FakeFx:
    async def usd_per_eur(self):
        return 1.25, "2026-11-17"  # 1 € = 1,25 $


class FakeReader:
    enabled = True

    def __init__(self, text=CHARIZARD_IT, error=None):
        self.text, self.error = text, error

    async def read_card(self, image, media_type="image/jpeg"):
        if self.error:
            raise VisionError(self.error)
        return parse_card_text(self.text)


@pytest.fixture
def make_client(catalog):
    def _make(reader=None, graded=None, pin=PIN):
        settings = Settings(app_pin=pin, allowed_wa_ids="393330000000", database_url="sqlite://",
                            web_dist="/nonexistent")
        sessions = make_session_factory(make_engine("sqlite://"))
        prices = PriceService(catalog, graded=graded if graded is not None else FakeGraded())
        c = Container(settings, sessions, whatsapp=None, engine=None, catalog=catalog, prices=prices,
                      matcher=CardMatcher(catalog), reader=reader or FakeReader(), fx=FakeFx(),
                      push=PushSender(sessions))
        return TestClient(create_app(c)), sessions
    return _make


def logged(make_client, **kw):
    client, sessions = make_client(**kw)
    assert client.post("/api/login", json={"pin": PIN}).status_code == 200
    return client, sessions


# --- accesso ---------------------------------------------------------------------------------------------------

def test_everything_requires_login(make_client):
    client, _ = make_client()
    for path in ("/api/me", "/api/search?q=pika", "/api/recent", "/api/tracking", "/api/cards/en/sv03.5-006"):
        assert client.get(path).status_code == 401


def test_login_sets_an_httponly_cookie_and_stores_only_its_hash(make_client):
    client, sessions = make_client()
    r = client.post("/api/login", json={"pin": PIN})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "pv_session=" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
    token = client.cookies.get("pv_session")
    with sessions() as s:
        stored = s.query(AppSession).one().token_hash
    assert stored != token and len(stored) == 64
    assert client.get("/api/me").json()["app"] == "PokeVault"


def test_wrong_pin_and_lockout(make_client):
    client, _ = make_client()
    for _ in range(5):
        assert client.post("/api/login", json={"pin": "000000"}).status_code == 401
    # Bloccato anche con il PIN giusto.
    assert client.post("/api/login", json={"pin": PIN}).status_code == 429


def test_app_disabled_without_pin(make_client):
    client, _ = make_client(pin="")
    assert client.post("/api/login", json={"pin": ""}).status_code == 503


def test_logout_revokes_the_session(make_client):
    client, _ = logged(make_client)
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


# --- ricerca ---------------------------------------------------------------------------------------------------

def test_search_by_name(make_client):
    client, _ = logged(make_client)
    cards = client.get("/api/search", params={"q": "Charizard ex", "lang": "en"}).json()["cards"]
    assert cards and all("Charizard" in c["name"] for c in cards)
    assert cards[0]["image"].endswith("/low.webp")


def test_search_by_code_and_number(make_client):
    client, _ = logged(make_client)
    cards = client.get("/api/search", params={"q": "MEW 006"}).json()["cards"]
    assert cards[0]["id"] == "sv03.5-006" and cards[0]["number_label"] == "006/165"


def test_search_by_pokedex_number(make_client):
    client, _ = logged(make_client)
    cards = client.get("/api/search", params={"q": "#0006"}).json()["cards"]
    assert cards == [] or all(c["catalog_lang"] in ("en", "ja") for c in cards)


def test_search_by_set(make_client):
    client, _ = logged(make_client)
    cards = client.get("/api/search", params={"q": "set:MEW", "lang": "en"}).json()["cards"]
    assert len(cards) > 100 and cards[0]["set_name"] == "151"


# --- scheda carta ----------------------------------------------------------------------------------------------

def test_card_detail(make_client):
    client, _ = logged(make_client)
    d = client.get("/api/cards/en/sv03.5-006").json()
    assert d["name"] == "Charizard ex" and d["image"].endswith("/high.webp")
    assert d["set"]["code"] == "MEW" and d["set"]["official"] == 165 and d["illustrator"] == "PLANETA Mochizuki"
    assert d["dex_ids"] == [6] and d["stats"]["hp"] == 330
    holo = d["variants"][0]
    assert holo["variant"] == "holo"
    intl, jp = holo["groups"][0], holo["groups"][1]
    assert intl["aggregated"] and intl["cardmarket"]["trend"] == 8.13 and intl["tcgplayer"]["market"] == 8.16
    assert jp["langs"] == ["ja"] and jp["estimated"] and jp["cardmarket"]["trend"] == 3.36
    names = [m["name"] for m in d["marketplaces"]]
    assert names == ["Cardmarket", "TCGplayer", "eBay"]
    assert "tcgplayer.com/product/502558" in d["marketplaces"][1]["url"]
    assert d["tracking"] == []


def test_card_not_found(make_client):
    client, _ = logged(make_client)
    assert client.get("/api/cards/en/nope-1").status_code == 404


def test_graded_in_euro(make_client):
    client, _ = logged(make_client)
    g = client.get("/api/cards/en/sv03.5-006/graded").json()
    assert g["available"] and g["usd_per_eur"] == 1.25
    psa10 = next(x for x in g["grades"] if x["company"] == "PSA" and x["grade"] == "10")
    assert psa10["price_usd"] == 50.14 and psa10["price_eur"] == 40.11


def test_recent_views(make_client):
    client, _ = logged(make_client)
    client.get("/api/cards/en/sv03.5-001")
    client.get("/api/cards/en/sv03.5-006")
    client.get("/api/cards/en/sv03.5-001")  # di nuovo: torna in cima, senza doppioni
    recent = client.get("/api/recent").json()["cards"]
    assert [r["id"] for r in recent] == ["sv03.5-001", "sv03.5-006"]


# --- scansione -------------------------------------------------------------------------------------------------

def test_scan_finds_the_card(make_client):
    client, _ = logged(make_client)
    r = client.post("/api/scan", content=b"\xff\xd8fake", headers={"content-type": "image/jpeg"}).json()
    assert r["found"] and r["confident"] and r["candidates"][0]["id"] == "sv03.5-006"
    assert r["read"]["set_code"] == "MEW"


def test_scan_errors_are_messages(make_client):
    client, _ = logged(make_client, reader=FakeReader(error="Il servizio che legge le foto non risponde"))
    r = client.post("/api/scan", content=b"x").json()
    assert not r["found"] and "non risponde" in r["message"]
    client, _ = logged(make_client, reader=FakeReader(text="Scontrino\nTotale 12,50"))
    assert "Non vedo una carta" in client.post("/api/scan", content=b"x").json()["message"]
    assert client.post("/api/scan", content=b"").status_code == 413


# --- carte seguite ---------------------------------------------------------------------------------------------

def test_track_from_the_app_with_psa(make_client):
    client, sessions = logged(make_client)
    r = client.put("/api/tracking", json={"card_id": "sv03.5-006", "catalog_lang": "en", "variant": "holo",
                                          "langs": ["it", "ja"], "psa": True})
    assert r.status_code == 200
    t = r.json()["tracking"]
    assert t["label"] == "Charizard ex · 151 006/165" and t["psa"] and t["langs"] == ["it", "ja"]
    with sessions() as s:
        active = sorted((x.source, x.langs) for x in s.query(TrackingTarget).filter_by(active=True))
        # PSA 10 per entrambe le stampe che hanno vendite: inglese (lingue internazionali) e giapponese.
        assert active == [("cardmarket", "it"), ("cardmarket", "ja"), ("psa10", "en"), ("psa10", "ja")]
    # Visibile nella scheda e nella lista; poi si toglie la PSA 10 senza toccare le lingue.
    assert client.get("/api/cards/en/sv03.5-006").json()["tracking"][0]["id"] == t["id"]
    client.put("/api/tracking", json={"card_id": "sv03.5-006", "catalog_lang": "en", "variant": "holo",
                                      "langs": ["it", "ja"], "psa": False})
    assert client.get("/api/tracking").json()["trackings"][0]["psa"] is False
    assert client.delete(f"/api/tracking/{t['id']}").status_code == 200
    assert client.get("/api/tracking").json()["trackings"] == []


def test_tracking_is_shared_with_the_whatsapp_user(make_client):
    client, sessions = logged(make_client)
    client.put("/api/tracking", json={"card_id": "sv03.5-006", "catalog_lang": "en", "variant": "holo",
                                      "langs": ["it"]})
    from cardbot.db import Tracking
    with sessions() as s:
        assert s.query(Tracking).one().user.wa_id == "393330000000"


def test_tracking_list_has_thumbnails(make_client):
    client, _ = logged(make_client)
    client.put("/api/tracking", json={"card_id": "sv03.5-006", "catalog_lang": "en", "variant": "holo",
                                      "langs": ["it"]})
    row = client.get("/api/tracking").json()["trackings"][0]
    assert row["image"] == "https://assets.tcgdex.net/en/sv/sv03.5/006/low.webp"


# --- carte Pocket e carte cinesi -------------------------------------------------------------------------------

def test_search_skips_pocket_cards(make_client):
    """Pokémon TCG Pocket è solo digitale: niente prezzi, quindi fuori dai risultati."""
    client, _ = logged(make_client)
    cards = client.get("/api/search", params={"q": "Gengar ex", "lang": "en"}).json()["cards"]
    assert [c["id"] for c in cards] == ["sv03.5-199"]


def test_search_chinese_by_code_uses_japanese_image_when_missing(make_client):
    client, _ = logged(make_client)
    cards = client.get("/api/search", params={"q": "SV2a 185", "lang": "zh"}).json()["cards"]
    assert cards[0]["id"] == "SV2a-185" and cards[0]["catalog_lang"] == "zh-tw"
    assert cards[0]["name"] == "噴火龍ex"
    assert cards[0]["image"] == "https://assets.tcgdex.net/ja/SV/SV2a/185/low.webp"


def test_search_chinese_set_fills_images(make_client):
    client, _ = logged(make_client)
    cards = client.get("/api/search", params={"q": "set:SV2a", "lang": "zh"}).json()["cards"]
    by_id = {c["id"]: c for c in cards}
    assert len(cards) > 200
    assert by_id["SV2a-006"]["image"] == "https://assets.tcgdex.net/zh-tw/SV/SV2a/006/low.webp"
    assert by_id["SV2a-185"]["image"] == "https://assets.tcgdex.net/ja/SV/SV2a/185/low.webp"


def test_chinese_card_detail_uses_the_japanese_twin_for_prices(make_client):
    client, _ = logged(make_client)
    d = client.get("/api/cards/zh-tw/SV2a-185").json()
    assert d["image"] == "https://assets.tcgdex.net/ja/SV/SV2a/185/high.webp"
    groups = d["variants"][0]["groups"]
    zh, ja = groups[0], groups[1]
    assert zh["langs"] == ["zh"] and zh["cardmarket"] is None and "giapponese" in zh["notes"][0]
    assert ja["langs"] == ["ja"] and ja["card_id"] == "SV2a-185" and ja["estimated"] is False
    assert ja["cardmarket"]["id_product"] == 719638


def test_catalog_down_gives_a_clear_message(make_client, catalog):
    import httpx

    async def down(*args, **kwargs):
        raise httpx.ConnectError("TCGdex non risponde")

    client, _ = logged(make_client)
    catalog.get_card = down
    r = client.get("/api/cards/en/sv03.5-006")
    assert r.status_code == 503 and "riprova" in r.json()["detail"]
