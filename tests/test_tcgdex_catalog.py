"""Catalogo TCGdex: cache e nuovi tentativi quando il servizio risponde 503 per qualche secondo."""

import httpx
import pytest
import respx

from cardbot.catalog import tcgdex
from cardbot.catalog.tcgdex import TCGdexCatalog

URL = "https://api.tcgdex.net/v2/en/cards/sv03.5-006"


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(tcgdex, "RETRY_DELAYS", (0, 0))


@respx.mock
async def test_retries_after_a_temporary_503():
    route = respx.get(URL).mock(side_effect=[httpx.Response(503), httpx.Response(200, json={"id": "sv03.5-006"})])
    catalog = TCGdexCatalog()
    assert (await catalog.get_card("en", "sv03.5-006"))["id"] == "sv03.5-006"
    assert route.call_count == 2
    # Ora è in cache: nessuna nuova richiesta.
    await catalog.get_card("en", "sv03.5-006")
    assert route.call_count == 2
    await catalog.aclose()


@respx.mock
async def test_gives_up_after_three_attempts():
    route = respx.get(URL).mock(return_value=httpx.Response(503))
    catalog = TCGdexCatalog()
    with pytest.raises(httpx.HTTPStatusError):
        await catalog.get_card("en", "sv03.5-006")
    assert route.call_count == 3
    await catalog.aclose()
