"""Prezzi delle carte gradate (PSA 10) da PokemonPriceTracker: vendite eBay e Fanatics Collect negli USA, in dollari.

Piano gratuito: 100 crediti al giorno. Ogni ricerca chiede una sola carta (limit=1) con le vendite gradate:
2 crediti. I risultati restano in memoria per CACHE_TTL, e le ricerche dalla chat si fermano quando restano
meno di CHAT_RESERVE crediti, per lasciarli al controllo giornaliero delle carte seguite.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from cardbot.prices.models import parse_datetime
from cardbot.recognition.matcher import normalize_number

log = logging.getLogger(__name__)

BASE_URL = "https://www.pokemonpricetracker.com/api/v2"
CACHE_TTL = 6 * 3600
CHAT_RESERVE = 20
GRADE = "psa10"


@dataclass
class GradedQuote:
    grade: str                  # "psa10"
    tcgplayer_id: str
    card_name: str
    set_name: str
    language: str               # "english" | "japanese"
    price: float | None         # prezzo di mercato "smart" (vendite recenti filtrate)
    confidence: str | None      # high | medium | low
    median: float | None
    sales: int
    trend: str | None           # up | down | stable
    updated: datetime | None
    currency: str = "USD"

    @property
    def has_sales(self) -> bool:
        return self.sales > 0 and self.price is not None

    @property
    def version(self) -> str:
        """Cambia solo quando il servizio ricalcola le vendite: serve a non duplicare gli snapshot."""
        return self.updated.isoformat() if self.updated else "unknown"


def quote_from_card(card: dict[str, Any], language: str) -> GradedQuote:
    stats = ((card.get("ebay") or {}).get("salesByGrade") or {}).get(GRADE) or {}
    smart = stats.get("smartMarketPrice") or {}
    price = smart.get("price") or stats.get("marketPrice7Day") or stats.get("medianPrice")
    name = (card.get("name") or "").split(" - ")[0]
    return GradedQuote(
        grade=GRADE, tcgplayer_id=str(card.get("tcgPlayerId") or ""), card_name=name,
        set_name=card.get("setName") or "", language=language,
        price=round(float(price), 2) if price else None, confidence=smart.get("confidence"),
        median=round(float(stats["medianPrice"]), 2) if stats.get("medianPrice") else None,
        sales=int(stats.get("count") or 0), trend=stats.get("marketTrend"),
        updated=parse_datetime(stats.get("lastMarketUpdate") or (card.get("ebay") or {}).get("updatedAt")),
    )


class GradedPrices:
    def __init__(self, api_key: str, client: httpx.AsyncClient | None = None, base_url: str = BASE_URL) -> None:
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._http = client or httpx.AsyncClient(timeout=30.0)
        self._cache: dict[tuple, tuple[float, GradedQuote | None]] = {}
        self.remaining: int | None = None  # crediti rimasti oggi (dall'header della risposta)

    @property
    def enabled(self) -> bool:
        return bool(self._key)

    def _cached(self, key: tuple) -> tuple[bool, GradedQuote | None]:
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            return True, hit[1]
        return False, None

    async def _get(self, params: dict[str, str]) -> Any:
        resp = await self._http.get(f"{self._base}/cards", params={**params, "includeEbay": "true"},
                                    headers={"Authorization": f"Bearer {self._key}"})
        remaining = resp.headers.get("X-Ratelimit-Daily-Remaining")
        if remaining and remaining.isdigit():
            self.remaining = int(remaining)
        if resp.status_code == 429:
            log.warning("PokemonPriceTracker: crediti giornalieri esauriti")
            return None
        resp.raise_for_status()
        return resp.json().get("data")

    async def by_id(self, tcgplayer_id: str, language: str = "english", for_chat: bool = False) -> GradedQuote | None:
        key = ("id", tcgplayer_id, language)
        found, value = self._cached(key)
        if found:
            return value
        if for_chat and self.remaining is not None and self.remaining < CHAT_RESERVE:
            return None
        data = await self._get({"tcgPlayerId": tcgplayer_id, "language": language, "limit": "1"})
        card = data[0] if isinstance(data, list) and data else data if isinstance(data, dict) else None
        quote = quote_from_card(card, language) if card else None
        self._cache[key] = (time.monotonic() + CACHE_TTL, quote)
        return quote

    async def search(self, name: str, number: str, total: str | None, language: str = "english",
                     for_chat: bool = False) -> GradedQuote | None:
        """Cerca per nome e numero ('Gengar ex 154/128') e accetta il risultato solo se il numero coincide."""
        label = f"{number}/{total}" if total else number
        key = ("search", name.lower(), label, language)
        found, value = self._cached(key)
        if found:
            return value
        if for_chat and self.remaining is not None and self.remaining < CHAT_RESERVE:
            return None
        data = await self._get({"search": f"{name} {label}", "language": language, "limit": "1"})
        card = data[0] if isinstance(data, list) and data else None
        quote = None
        if card and normalize_number((card.get("cardNumber") or "").split("/")[0]) == normalize_number(number):
            quote = quote_from_card(card, language)
            self._cache[("id", quote.tcgplayer_id, language)] = (time.monotonic() + CACHE_TTL, quote)
        self._cache[key] = (time.monotonic() + CACHE_TTL, quote)
        return quote
