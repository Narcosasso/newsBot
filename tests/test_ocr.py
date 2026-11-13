"""Lettura delle foto con Google Vision: parsing del testo riconosciuto e chiamata al servizio (mockata)."""

import httpx
import pytest
import respx

from cardbot.recognition.matcher import CardMatcher
from cardbot.recognition.ocr import ANNOTATE_URL, METADATA_TOKEN_URL, GoogleVisionReader, parse_card_text
from cardbot.recognition.vision import VisionError

GENGAR_EN = """STAGE 2
Gengar ex
HP 310
Evolves from Haunter
Ability Shadow Hide
weakness x2 resistance retreat
Illus. CHORISO
H 30C EN 154/128
©2026 Pokémon / Nintendo / Creatures / GAME FREAK"""

CHARIZARD_IT = """FASE 2
Charizard-ex
PS 330
Si evolve da Charmeleon
Ala Coraggiosa 60+
debolezza resistenza ritirata
Illus. PLANETA Mochizuki
G MEW IT 006/165"""

GENGAR_JA = """2進化
ゲンガーex
HP 310
弱点 抵抗力 にげる
M6a 131/103 SAR"""

CHARIZARD_BASE = """Charizard
120 HP
STAGE 2 Evolved from Charmeleon
Energy Burn
weakness resistance retreat cost
Illus. Mitsuhiro Arita
4/102 ★ ©1995, 96, 98 Nintendo"""


@pytest.mark.parametrize("text,lang,name,code,number,total", [
    (GENGAR_EN, "en", "Gengar ex", "30C", "154", "128"),
    (CHARIZARD_IT, "it", "Charizard-ex", "MEW", "006", "165"),
    (GENGAR_JA, "ja", "ゲンガーex", "M6a", "131", "103"),
    (CHARIZARD_BASE, "en", "Charizard", None, "4", "102"),
])
def test_parse_card_text(text, lang, name, code, number, total):
    r = parse_card_text(text)
    assert r.is_pokemon_card
    assert (r.language, r.name, r.set_code, r.number, r.set_total) == (lang, name, code, number, total)
    assert r.variant_hint == "unknown"  # l'OCR non vede il riflesso: la variante la chiede il bot


def test_confidence_depends_on_what_was_read():
    assert parse_card_text(CHARIZARD_IT).confidence >= 0.8
    assert 0.6 <= parse_card_text(CHARIZARD_BASE).confidence < 0.8


@pytest.mark.parametrize("text", ["", "Ciao mamma\nfoto delle vacanze al mare", "Scontrino\nTotale 12,50"])
def test_not_a_card(text):
    r = parse_card_text(text)
    assert not r.is_pokemon_card and r.confidence == 0.0


async def test_ocr_text_finds_the_card_in_the_catalog(catalog):
    r = await CardMatcher(catalog).match(parse_card_text(CHARIZARD_IT))
    assert r.confident and r.best.card_id == "sv03.5-006" and r.best.catalog_lang == "it"


def _annotate(text):
    return httpx.Response(200, json={"responses": [{"fullTextAnnotation": {"text": text}}]})


@respx.mock
async def test_reader_uses_the_service_account_token_on_cloud_run():
    respx.get(METADATA_TOKEN_URL).mock(return_value=httpx.Response(
        200, json={"access_token": "tok", "expires_in": 3600}))
    route = respx.post(ANNOTATE_URL).mock(return_value=_annotate(CHARIZARD_IT))
    reader = GoogleVisionReader()
    result = await reader.read_card(b"\xff\xd8")
    assert result.set_code == "MEW"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer tok"
    assert b'"TEXT_DETECTION"' in request.content
    await reader.read_card(b"\xff\xd8")  # il token resta in cache: una sola chiamata al metadata server
    assert respx.calls.call_count == 3


@respx.mock
async def test_reader_with_api_key_for_local_use():
    route = respx.post(ANNOTATE_URL).mock(return_value=_annotate(GENGAR_EN))
    result = await GoogleVisionReader(api_key="k").read_card(b"x")
    assert result.number == "154" and route.calls.last.request.url.params["key"] == "k"


@respx.mock
async def test_reader_not_configured_outside_cloud_run():
    respx.get(METADATA_TOKEN_URL).mock(side_effect=httpx.ConnectError("no metadata"))
    with pytest.raises(VisionError, match="non configurata"):
        await GoogleVisionReader().read_card(b"x")


@respx.mock
async def test_reader_service_errors_become_friendly_messages():
    respx.post(ANNOTATE_URL).mock(return_value=httpx.Response(403, json={"error": {"message": "API disabled"}}))
    with pytest.raises(VisionError, match="errore"):
        await GoogleVisionReader(api_key="k").read_card(b"x")


def test_make_reader_choices():
    from cardbot.config import Settings
    from cardbot.recognition.readers import make_reader
    from cardbot.recognition.vision import CardVision, DisabledVision

    assert isinstance(make_reader(Settings(photo_reader="google")), GoogleVisionReader)
    assert isinstance(make_reader(Settings(photo_reader="off")), DisabledVision)
    assert isinstance(make_reader(Settings(photo_reader="claude", anthropic_api_key="")), DisabledVision)
    assert isinstance(make_reader(Settings(photo_reader="claude", anthropic_api_key="k")), CardVision)
