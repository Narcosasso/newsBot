"""Cambio dollaro → euro dal riferimento giornaliero ufficiale della BCE (gratuito, nessuna chiave)."""

from __future__ import annotations

import logging
import re
import time

import httpx

log = logging.getLogger(__name__)

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
TTL = 12 * 3600


class FxRates:
    def __init__(self, client: httpx.AsyncClient | None = None, url: str = ECB_URL) -> None:
        self._http = client or httpx.AsyncClient(timeout=15.0)
        self._url = url
        self._cache: tuple[float, float | None, str | None] | None = None  # (scadenza, usd_per_eur, data)

    async def usd_per_eur(self) -> tuple[float | None, str | None]:
        """(quanti dollari vale 1 euro, data del cambio). (None, None) se la BCE non risponde."""
        if self._cache and self._cache[0] > time.monotonic():
            return self._cache[1], self._cache[2]
        rate = day = None
        try:
            resp = await self._http.get(self._url)
            resp.raise_for_status()
            m = re.search(r"currency=['\"]USD['\"]\s+rate=['\"]([\d.]+)['\"]", resp.text)
            d = re.search(r"time=['\"](\d{4}-\d{2}-\d{2})['\"]", resp.text)
            rate = float(m.group(1)) if m else None
            day = d.group(1) if d else None
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Cambio BCE non disponibile: %s", exc)
        # Anche un errore resta in cache per un po': niente richieste a raffica se la BCE non risponde.
        self._cache = (time.monotonic() + (TTL if rate else 900), rate, day)
        return rate, day

    async def usd_to_eur(self, amount: float | None) -> float | None:
        rate, _ = await self.usd_per_eur()
        if amount is None or not rate:
            return None
        return round(amount / rate, 2)
