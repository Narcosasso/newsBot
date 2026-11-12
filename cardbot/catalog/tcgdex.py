"""Client asincrono per l'API pubblica TCGdex (https://tcgdex.dev), gratuita e senza chiave.

- Cache in memoria con TTL: l'elenco dei set cambia raramente, i prezzi (inclusi nella carta) una volta al giorno.
- Limite di richieste al secondo configurabile, per non stressare il servizio.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote

import httpx

SETS_TTL = 24 * 3600
CARD_TTL = 3 * 3600
SEARCH_TTL = 6 * 3600


class TCGdexCatalog:
    def __init__(
        self,
        base_url: str = "https://api.tcgdex.net/v2",
        max_rps: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(
            timeout=20.0, headers={"User-Agent": "cardbot/0.1 (personal price tracker)"}
        )
        self._min_interval = 1.0 / max_rps if max_rps > 0 else 0.0
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        self._cache: dict[str, tuple[float, Any]] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, ttl: float, params: dict[str, str] | None = None) -> Any:
        key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        hit = self._cache.get(key)
        now = time.monotonic()
        if hit and hit[0] > now:
            return hit[1]
        async with self._lock:
            wait = self._last_request + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()
        resp = await self._client.get(f"{self._base}{path}", params=params)
        if resp.status_code == 404:
            data = None
        else:
            resp.raise_for_status()
            data = resp.json()
        self._cache[key] = (time.monotonic() + ttl, data)
        return data

    async def list_sets(self, lang: str) -> list[dict[str, Any]]:
        return await self._get(f"/{lang}/sets", SETS_TTL) or []

    async def get_set(self, lang: str, set_id: str) -> dict[str, Any] | None:
        return await self._get(f"/{lang}/sets/{quote(set_id)}", SETS_TTL)

    async def get_card(self, lang: str, card_id: str) -> dict[str, Any] | None:
        return await self._get(f"/{lang}/cards/{quote(card_id)}", CARD_TTL)

    async def search_cards(self, lang: str, filters: dict[str, str]) -> list[dict[str, Any]]:
        return await self._get(f"/{lang}/cards", SEARCH_TTL, params=filters) or []

    async def search_sets(self, lang: str, filters: dict[str, str]) -> list[dict[str, Any]]:
        return await self._get(f"/{lang}/sets", SETS_TTL, params=filters) or []
