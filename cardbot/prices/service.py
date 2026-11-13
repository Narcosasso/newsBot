"""Prezzi per lingua da fonti gratuite (prezzi Cardmarket e TCGplayer inclusi nelle carte TCGdex).

Cosa è davvero "per lingua" con dati gratuiti:
- ITA/ENG/DEU/FRA/SPA/POR: Cardmarket le vende come un unico prodotto, quindi il prezzo è AGGREGATO su queste
  lingue. Per ENG mostriamo in più TCGplayer (mercato USA, quasi solo carte inglesi).
- JAP: le carte giapponesi sono prodotti Cardmarket separati, quindi il prezzo è specifico.
- KOR/CIN: nessuna fonte gratuita con prezzi.
"""

from __future__ import annotations

import logging

from typing import Any

from cardbot.catalog.base import Catalog
from cardbot.langs import INTERNATIONAL
from cardbot.prices.models import LangQuote, cardmarket_quote, tcgplayer_quote
from cardbot.variants import variant_entry

log = logging.getLogger(__name__)

ASIAN_CATALOGS = {"ja", "zh-tw"}

def _shared_product(card: dict[str, Any], entry: dict[str, Any] | None) -> bool:
    """True se la variante condivide il prodotto Cardmarket con un'altra variante (caso tipico: reverse)."""
    if not entry:
        return True
    pid = (entry.get("thirdParty") or {}).get("cardmarket")
    others = [v for v in card.get("variants_detailed") or [] if v is not entry]
    return any((v.get("thirdParty") or {}).get("cardmarket") == pid for v in others)


def card_label(card: dict[str, Any]) -> str:
    s = card.get("set") or {}
    total = (s.get("cardCount") or {}).get("official")
    num = f"{card.get('localId', '')}/{total}" if total else card.get("localId", "")
    return f"{card.get('name', '')} · {s.get('name', s.get('id', ''))} {num}".strip()


def quote_card(card: dict[str, Any], variant: str, langs: list[str], with_tcgplayer: bool,
               catalog_lang: str) -> LangQuote:
    entry = variant_entry(card, variant)
    pricing = (entry or {}).get("pricing") or card.get("pricing") or {}
    shared = _shared_product(card, entry)
    cm = cardmarket_quote(pricing.get("cardmarket"), variant, shared)
    tp = tcgplayer_quote(pricing.get("tcgplayer"), variant) if with_tcgplayer else None
    return LangQuote(langs=langs, card_id=card.get("id"), card_label=card_label(card), cardmarket=cm,
                     tcgplayer=tp, catalog_lang=catalog_lang, shared_product=shared)


def tcgplayer_id(card: dict[str, Any], variant: str) -> str | None:
    """ID TCGplayer della carta (per i prezzi PSA 10), se TCGdex lo conosce."""
    entry = variant_entry(card, variant) or {}
    tid = (entry.get("thirdParty") or {}).get("tcgplayer")
    if not tid:
        for v in card.get("variants_detailed") or []:
            tid = tid or (v.get("thirdParty") or {}).get("tcgplayer")
    if not tid:
        for price in ((card.get("pricing") or {}).get("tcgplayer") or {}).values():
            if isinstance(price, dict) and price.get("productId"):
                tid = price["productId"]
                break
    return str(tid) if tid else None


class PriceService:
    def __init__(self, catalog: Catalog, graded: Any = None) -> None:
        self._catalog = catalog
        self._graded = graded  # GradedPrices (PokemonPriceTracker) oppure None

    @property
    def graded_enabled(self) -> bool:
        return bool(self._graded and self._graded.enabled)

    async def graded_quote(self, card_id: str, catalog_lang: str, variant: str, for_chat: bool = True):
        """Prezzo PSA 10 della carta: per le carte internazionali quello della stampa inglese."""
        if not self.graded_enabled:
            return None
        card = await self._catalog.get_card(catalog_lang, card_id)
        if card is None:
            return None
        try:
            if catalog_lang in ASIAN_CATALOGS:
                language = "japanese" if catalog_lang == "ja" else "english"
                eq, _ = await self.find_equivalent(card, "en")
                name = (eq or {}).get("name")
                tid = None
            else:
                language = "english"
                en = await self._catalog.get_card("en", card_id) or card
                name, tid = en.get("name"), tcgplayer_id(en, variant)
            if tid:
                return await self._graded.by_id(tid, language, for_chat=for_chat)
            if not name:
                return None
            total = ((card.get("set") or {}).get("cardCount") or {}).get("official")
            return await self._graded.search(name, card.get("localId", ""), str(total) if total else None,
                                             language, for_chat=for_chat)
        except Exception as exc:  # una fonte in più non deve mai bloccare la risposta principale
            log.warning("Prezzo PSA 10 non disponibile per %s: %s", card_id, exc)
            return None

    async def quotes(self, card_id: str, catalog_lang: str, variant: str, langs: list[str],
                     with_graded: bool = True) -> list[LangQuote]:
        out = await self._cardmarket_quotes(card_id, catalog_lang, variant, langs)
        if with_graded and self.graded_enabled:
            for q in out:
                if q.card_id and q.catalog_lang:
                    q.graded = await self.graded_quote(q.card_id, q.catalog_lang, variant)
        return out

    async def _cardmarket_quotes(self, card_id: str, catalog_lang: str, variant: str,
                                 langs: list[str]) -> list[LangQuote]:
        card = await self._catalog.get_card(catalog_lang, card_id)
        if card is None:
            return [LangQuote(langs=langs, card_id=None, card_label=None, notes=["Carta non trovata nel catalogo."])]

        intl_langs = [lang for lang in langs if lang in INTERNATIONAL]
        is_asian = catalog_lang in ASIAN_CATALOGS
        out: list[LangQuote] = []

        if intl_langs:
            intl_card, estimated = (card, False)
            if is_asian:
                intl_card, estimated = await self.find_equivalent(card, "en")
            if intl_card is None:
                out.append(LangQuote(langs=intl_langs, card_id=None, card_label=None,
                                     notes=["Equivalente internazionale non trovato nel catalogo."]))
            else:
                q = quote_card(intl_card, variant, intl_langs, with_tcgplayer="en" in intl_langs,
                               catalog_lang="en" if is_asian else catalog_lang)
                q.aggregated = True
                q.estimated_equivalent = estimated
                out.append(q)

        if "ja" in langs:
            if catalog_lang == "ja":
                out.append(quote_card(card, variant, ["ja"], with_tcgplayer=False, catalog_lang="ja"))
            else:
                jp_card, estimated = await self.find_equivalent(card, "ja")
                if jp_card is None:
                    out.append(LangQuote(langs=["ja"], card_id=None, card_label=None,
                                         notes=["Equivalente giapponese non trovato nel catalogo."]))
                else:
                    q = quote_card(jp_card, variant, ["ja"], with_tcgplayer=False, catalog_lang="ja")
                    q.estimated_equivalent = estimated
                    out.append(q)

        for lang in ("ko", "zh"):
            if lang in langs:
                out.append(LangQuote(langs=[lang], card_id=None, card_label=None,
                                     notes=["Nessuna fonte gratuita pubblica i prezzi di questa lingua."]))
        return out

    async def find_equivalent(self, card: dict[str, Any], target_lang: str) -> tuple[dict[str, Any] | None, bool]:
        """Stessa carta in un altro catalogo: stesso Pokémon, illustratore e PS; a parità, stesso numero e rarità.

        Restituisce (carta, stimato). È sempre una stima: i set giapponesi e internazionali non coincidono.
        """
        dex = card.get("dexId") or []
        illustrator = card.get("illustrator")
        if not dex or not illustrator:
            return None, True
        filters = {"dexId": f"eq:{dex[0]}", "illustrator": illustrator}
        if card.get("hp"):
            filters["hp"] = f"eq:{card['hp']}"
        results = await self._catalog.search_cards(target_lang, filters)
        if not results:
            return None, True
        same_number = [r for r in results if r.get("localId") == card.get("localId")]
        pool = same_number or results
        if len(pool) > 1:
            details = [await self._catalog.get_card(target_lang, r["id"]) for r in pool]
            same_rarity = [d for d in details if d and d.get("rarity") == card.get("rarity")]
            pool_cards = same_rarity or [d for d in details if d]
        else:
            pool_cards = [await self._catalog.get_card(target_lang, pool[0]["id"])]
        pool_cards = [c for c in pool_cards if c]
        return (pool_cards[0] if pool_cards else None), True
