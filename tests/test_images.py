"""Foto e loghi di riserva da Scrydex: codici dei set e scarto del retro carta che Scrydex dà per le mancanti."""

import httpx
import respx

from cardbot.images import BASE, ImageResolver, card_base, logo_url, scrydex_set, sized


def test_set_codes():
    assert scrydex_set("sv03.5", "en") == "sv3pt5"
    assert scrydex_set("me02.5", "en") == "me2pt5"
    assert scrydex_set("sv01", "en") == "sv1"
    assert scrydex_set("30th", "en") == "me55"
    assert scrydex_set("mep", "en") == "mep"
    assert scrydex_set("M5", "ja") == "m5_ja"
    assert scrydex_set("SV2a", "zh-tw") == "sv2a_ja"
    assert card_base("30th-154", "en") == f"{BASE}/me55-154"
    assert card_base("M5-050", "ja") == f"{BASE}/m5_ja-50"
    assert logo_url("me06", "en") == f"{BASE}/me6-logo/medium"
    assert sized(f"{BASE}/me55-154/large", "low") == f"{BASE}/me55-154/small"
    assert sized(f"{BASE}/me55-154", "high") == f"{BASE}/me55-154/medium"


@respx.mock
async def test_placeholder_card_back_is_rejected_and_results_cached():
    real = respx.head(f"{BASE}/me55-154/small").mock(
        return_value=httpx.Response(200, headers={"etag": '"cfvEovL2fr_23"', "content-length": "57490"}))
    respx.head(f"{BASE}/me55-999/small").mock(
        return_value=httpx.Response(200, headers={"etag": '"cfl2loWl84E8tUjrC-Q-I0D0JhhkQ"', "content-length": "45551"}))
    r = ImageResolver(httpx.AsyncClient())
    assert await r.card("30th-154", "en") == f"{BASE}/me55-154"
    assert await r.card("30th-999", "en") is None
    await r.card("30th-154", "en")
    assert real.call_count == 1                      # seconda volta: dalla memoria
    rows = [{"id": "30th-154", "catalog_lang": "en", "image": None}, {"id": "x-1", "catalog_lang": "en", "image": "ok"}]
    await r.fill(rows)
    assert rows[0]["image"] == f"{BASE}/me55-154/small" and rows[1]["image"] == "ok"
