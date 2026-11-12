"""Fonti dei prezzi per il job giornaliero.

1. Price guide pubblico di Cardmarket (un file JSON per tutti i prodotti Pokémon, rigenerato una volta al giorno
   verso le 02:50 ora italiana). Una sola richiesta al giorno, condizionale con ETag: se il file non è cambiato il
   server risponde 304 e non si scarica nulla.
2. Fallback: TCGdex, una richiesta per carta tracciata (con lo stesso limite di richieste al secondo della chat).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from cardbot.catalog.base import Catalog
from cardbot.variants import variant_entry

log = logging.getLogger(__name__)

PRICE_GUIDE_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json"


@dataclass
class PriceData:
    source: str
    version: str                                  # cambia solo quando la fonte pubblica dati nuovi
    entries: dict[int, dict[str, Any]] = field(default_factory=dict)  # idProduct -> campi Cardmarket
    etag: str | None = None


class CardmarketPriceGuide:
    name = "cardmarket_price_guide"

    def __init__(self, url: str = PRICE_GUIDE_URL, client: httpx.AsyncClient | None = None) -> None:
        self._url = url
        self._http = client or httpx.AsyncClient(timeout=120.0, headers={"User-Agent": "cardbot/0.1"})

    async def fetch(self, etag: str | None = None) -> PriceData | None:
        """None se il file non è cambiato dall'ETag indicato."""
        headers = {"If-None-Match": etag} if etag else {}
        resp = await self._http.get(self._url, headers=headers)
        if resp.status_code == 304:
            return None
        resp.raise_for_status()
        data = resp.json()
        entries = {int(e["idProduct"]): e for e in data.get("priceGuides") or [] if e.get("idProduct")}
        return PriceData(source=self.name, version=str(data.get("createdAt") or resp.headers.get("etag")),
                         entries=entries, etag=resp.headers.get("etag"))


class TCGdexPrices:
    """Fallback: legge i prezzi Cardmarket dalla carta TCGdex di ogni target."""

    name = "tcgdex"

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    async def fetch_for(self, targets: list[tuple[str, str, str]]) -> PriceData:
        """targets: (catalog_lang, card_id, variant)."""
        entries: dict[int, dict[str, Any]] = {}
        versions: set[str] = set()
        for lang, card_id, variant in sorted(set(targets)):
            card = await self._catalog.get_card(lang, card_id)
            if not card:
                continue
            entry = variant_entry(card, variant) or {}
            cm = ((entry.get("pricing") or card.get("pricing") or {}).get("cardmarket")) or {}
            if cm.get("idProduct"):
                entries[int(cm["idProduct"])] = cm
                if cm.get("updated"):
                    versions.add(cm["updated"][:10])  # TCGdex aggiorna una volta al giorno
        return PriceData(source=self.name, version=max(versions) if versions else "unknown", entries=entries)
