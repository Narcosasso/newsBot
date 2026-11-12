"""Interfaccia del catalogo carte (implementata da TCGdex; nei test da un fake su fixture)."""

from __future__ import annotations

from typing import Any, Protocol

# Lingua della carta -> lingua del catalogo TCGdex in cui cercarla.
# Le carte coreane usano gli stessi codici set e la stessa numerazione delle giapponesi, ma TCGdex
# non ha le carte coreane: le cerchiamo nel catalogo giapponese.
_CATALOG_LANG = {
    "en": "en",
    "it": "it",
    "fr": "fr",
    "de": "de",
    "es": "es",
    "pt": "pt-br",
    "ja": "ja",
    "ko": "ja",
    "zh": "zh-tw",
}


def catalog_lang_for(card_lang: str) -> str:
    return _CATALOG_LANG.get(card_lang, "en")


class Catalog(Protocol):
    async def list_sets(self, lang: str) -> list[dict[str, Any]]: ...

    async def get_set(self, lang: str, set_id: str) -> dict[str, Any] | None: ...

    async def get_card(self, lang: str, card_id: str) -> dict[str, Any] | None: ...

    async def search_cards(self, lang: str, filters: dict[str, str]) -> list[dict[str, Any]]: ...

    async def search_sets(self, lang: str, filters: dict[str, str]) -> list[dict[str, Any]]: ...
