"""Scheda carta per l'app: dati, set, prezzi per variante e lingua, gradate (in euro), link ai marketplace."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import quote_plus

from cardbot.catalog.base import Catalog
from cardbot.langs import NAMES_IT, flag
from cardbot.prices.fx import FxRates
from cardbot.prices.models import CardmarketQuote, LangQuote, TCGplayerQuote
from cardbot.prices.service import PriceService, tcgplayer_id
from cardbot.variants import LABELS_IT, variants_of
from cardbot.web.search import _logo, image_url


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def cardmarket_json(cm: CardmarketQuote | None) -> dict[str, Any] | None:
    if cm is None or not cm.has_data:
        return None
    return {
        "currency": cm.currency, "low": cm.low, "trend": cm.trend, "avg": cm.avg, "avg1": cm.avg1,
        "avg7": cm.avg7, "avg30": cm.avg30, "change_7d": cm.change_7d_pct, "change_30d": cm.change_30d_pct,
        "updated": iso(cm.updated), "id_product": cm.id_product,
    }


def tcgplayer_json(tp: TCGplayerQuote | None) -> dict[str, Any] | None:
    if tp is None:
        return None
    return {"currency": tp.currency, "market": tp.market, "low": tp.low, "updated": iso(tp.updated)}


def group_json(q: LangQuote) -> dict[str, Any]:
    return {
        "langs": q.langs,
        "label": " · ".join(f"{flag(x)} {NAMES_IT[x]}" for x in q.langs),
        "card_id": q.card_id, "catalog_lang": q.catalog_lang, "card_label": q.card_label,
        "aggregated": q.aggregated, "estimated": q.estimated_equivalent,
        "cardmarket": cardmarket_json(q.cardmarket), "tcgplayer": tcgplayer_json(q.tcgplayer), "notes": q.notes,
    }


def card_label(card: dict[str, Any]) -> str:
    """Stessa forma usata dal bot per le carte seguite: 'Gengar ex · 30th Celebration 154/128'."""
    s = card.get("set") or {}
    total = (s.get("cardCount") or {}).get("official")
    num = f"{card.get('localId', '')}/{total}" if total else card.get("localId", "")
    return f"{card.get('name', '')} · {s.get('name', s.get('id', ''))} {num}".strip()


def marketplaces(card: dict[str, Any], en_card: dict[str, Any] | None, variant: str) -> list[dict[str, str]]:
    s = card.get("set") or {}
    total = (s.get("cardCount") or {}).get("official")
    number = f"{card.get('localId', '')}/{total}" if total else card.get("localId", "")
    query = quote_plus(f"{(en_card or card).get('name', '')} {number}")
    links = [{"name": "Cardmarket",
              "url": f"https://www.cardmarket.com/it/Pokemon/Products/Search?searchString={query}"}]
    tid = tcgplayer_id(en_card, variant) if en_card else None
    if tid:
        links.append({"name": "TCGplayer", "url": f"https://www.tcgplayer.com/product/{tid}"})
    links.append({"name": "eBay", "url": f"https://www.ebay.it/sch/i.html?_nkw={query}"})
    return links


async def card_detail(catalog: Catalog, prices: PriceService, lang: str, card_id: str) -> dict[str, Any] | None:
    card = await catalog.get_card(lang, card_id)
    if card is None:
        return None
    set_brief = card.get("set") or {}
    set_detail = await catalog.get_set(lang, set_brief.get("id", "")) or {}
    en_card = card if lang == "en" else (await catalog.get_card("en", card_id) if lang not in ("ja", "zh-tw")
                                         else None)
    variants = variants_of(card) or ["normal"]
    price_langs = ["ja", "it", "en"] if lang == "ja" else ["it", "en", "ja"]
    by_variant = []
    for v in variants:
        quotes = await prices.quotes(card_id, lang, v, price_langs, with_graded=False)
        by_variant.append({"variant": v, "label": LABELS_IT.get(v, v), "groups": [group_json(q) for q in quotes]})

    serie = set_detail.get("serie") or {}
    total = (set_detail.get("cardCount") or set_brief.get("cardCount") or {})
    return {
        "id": card["id"], "catalog_lang": lang, "name": card.get("name", ""), "label": card_label(card),
        "image": image_url(card.get("image"), "high"), "image_small": image_url(card.get("image")),
        "number": card.get("localId", ""), "rarity": card.get("rarity"), "illustrator": card.get("illustrator"),
        "dex_ids": card.get("dexId") or [], "category": card.get("category"),
        "stats": {
            "hp": card.get("hp"), "types": card.get("types") or [], "stage": card.get("stage"),
            "evolve_from": card.get("evolveFrom"), "weaknesses": card.get("weaknesses") or [],
            "resistances": card.get("resistances") or [], "retreat": card.get("retreat"),
            "regulation_mark": card.get("regulationMark"),
        },
        "set": {
            "id": set_detail.get("id", set_brief.get("id")), "name": set_detail.get("name", set_brief.get("name")),
            "code": (set_detail.get("abbreviation") or {}).get("official") or set_detail.get("id"),
            "logo": _logo(set_detail or set_brief), "serie": serie.get("name"),
            "release_date": set_detail.get("releaseDate"), "official": total.get("official"),
            "total": total.get("total"),
        },
        "variants": by_variant,
        "marketplaces": marketplaces(card, en_card, variants[0]),
    }


async def graded_detail(prices: PriceService, fx: FxRates, lang: str, card_id: str,
                        variant: str) -> dict[str, Any]:
    if not prices.graded_enabled:
        return {"available": False, "reason": "I prezzi delle carte gradate non sono configurati."}
    g = await prices.graded_quote(card_id, lang, variant, for_chat=True)
    if g is None:
        return {"available": False, "reason": "Nessun prezzo gradato trovato (o limite giornaliero raggiunto)."}
    rate, rate_day = await fx.usd_per_eur()

    def eur(v: float | None) -> float | None:
        return round(v / rate, 2) if (v is not None and rate) else None

    grades = [{"company": s.company, "grade": s.grade, "price_usd": s.price, "price_eur": eur(s.price),
               "median_usd": s.median, "median_eur": eur(s.median), "sales": s.sales, "trend": s.trend}
              for s in g.grades]
    return {
        "available": True, "source": "PokemonPriceTracker (vendite eBay e Fanatics, USA)",
        "print": "giapponese" if g.language == "japanese" else "inglese", "tcgplayer_id": g.tcgplayer_id,
        "updated": iso(g.updated), "usd_per_eur": rate, "fx_date": rate_day,
        "companies": sorted({s["company"] for s in grades}, key=["PSA", "CGC", "BGS", "SGC", "TAG", "ACE", "AGS",
                                                                   "PCG"].index),
        "grades": grades,
    }
