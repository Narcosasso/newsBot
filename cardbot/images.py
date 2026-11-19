"""Foto delle carte e loghi dei set quando TCGdex non li ha (carte nuove, promo, quasi tutto il giapponese).

Riserva: le immagini pubbliche di Scrydex (le stesse dell'export di MyDex), con i loro codici set
(sv03.5 -> sv3pt5, 30th -> me55, M5 giapponese -> m5_ja). Se un'immagine non esiste Scrydex risponde comunque
200 con il retro di una carta: lo riconosciamo dalla sua impronta (ETag) e dalla dimensione, e lo scartiamo.
"""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

log = logging.getLogger(__name__)

BASE = "https://images.scrydex.com/pokemon"
SET_ALIASES = {"30th": "me55", "30th-c": "me55c", "2022swsh": "mcd22", "2021swsh": "mcd21"}
PLACEHOLDER_ETAG = '"cfl2loWl84E8tUjrC-Q-I0D0J'      # inizio dell'ETag del retro carta, uguale in ogni formato
PLACEHOLDER_SIZES = {45551, 82623, 186316}           # small, medium, large


def scrydex_set(set_id: str, catalog_lang: str) -> str:
    if catalog_lang in ("ja", "zh-tw"):  # le cinesi usano i codici dei set giapponesi
        return f"{set_id.lower()}_ja"
    if set_id in SET_ALIASES:
        return SET_ALIASES[set_id]
    if m := re.match(r"^([a-z]+)0*(\d+)(\.5)?$", set_id):
        return f"{m.group(1)}{int(m.group(2))}{'pt5' if m.group(3) else ''}"
    return set_id.lower()


def card_base(card_id: str, catalog_lang: str) -> str | None:
    """Base dell'immagine Scrydex della carta (senza formato), es. https://…/pokemon/me55-154."""
    set_id, _, number = card_id.rpartition("-")
    if not set_id or not number:
        return None
    num = number.lstrip("0") or "0"
    return f"{BASE}/{scrydex_set(set_id, catalog_lang)}-{num}"


def logo_url(set_id: str, catalog_lang: str) -> str:
    return f"{BASE}/{scrydex_set(set_id, catalog_lang)}-logo/medium"


def is_scrydex(url: str | None) -> bool:
    return bool(url) and url.startswith(BASE)


def sized(url: str, quality: str) -> str:
    """Formato dell'immagine Scrydex: "low" -> small (244 px), "high" -> medium (365 px); mai large (1 MB)."""
    base = re.sub(r"/(small|medium|large)$", "", url)
    return f"{base}/{'small' if quality == 'low' else 'medium'}"


class ImageResolver:
    """Verifica (una volta, poi in memoria) che l'immagine Scrydex di una carta esista davvero."""

    def __init__(self, client: httpx.AsyncClient | None = None, concurrency: int = 12) -> None:
        self._http = client or httpx.AsyncClient(timeout=6.0, headers={"User-Agent": "cardbot/0.1"})
        self._known: dict[str, bool] = {}
        self._sem = asyncio.Semaphore(concurrency)

    async def exists(self, base: str) -> bool:
        if base in self._known:
            return self._known[base]
        async with self._sem:
            try:
                resp = await self._http.head(f"{base}/small")
                etag = resp.headers.get("etag", "")
                size = int(resp.headers.get("content-length") or 0)
                ok = resp.status_code == 200 and not etag.startswith(PLACEHOLDER_ETAG) and size not in PLACEHOLDER_SIZES
            except Exception as exc:  # rete: non lo ricordiamo, si riproverà
                log.info("Immagine %s non verificabile: %s", base, exc)
                return False
        self._known[base] = ok
        return ok

    async def card(self, card_id: str, catalog_lang: str) -> str | None:
        base = card_base(card_id, catalog_lang)
        return base if base and await self.exists(base) else None

    async def fill(self, rows: list[dict], limit: int = 250) -> None:
        """Completa la foto delle carte (riepiloghi di ricerca o set) che non ne hanno una."""
        missing = [r for r in rows if not r.get("image")][:limit]
        found = await asyncio.gather(*(self.card(r["id"], r["catalog_lang"]) for r in missing))
        for r, base in zip(missing, found):
            if base:
                r["image"] = sized(base, "low")


resolver = ImageResolver()
