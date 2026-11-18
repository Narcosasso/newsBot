"""Ricerca carte per l'app: nome, #Pokédex, illustratore, set:codice, oppure codice e numero ("30C 154").

Cataloghi: inglese (carte internazionali), giapponese e cinese tradizionale (TCGdex "zh-tw", che usa gli stessi
codici set e numeri delle giapponesi). Le carte di Pokémon TCG Pocket (solo digitali, senza prezzi) sono escluse.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from cardbot.catalog.base import Catalog
from cardbot.recognition.matcher import CardMatcher, normalize_number
from cardbot.recognition.text_query import parse_query

MAX_RESULTS = 60
JAPANESE = re.compile(r"[぀-ヿ一-鿿]")
KANA = re.compile(r"[぀-ヿ]")
POCKET_SET = re.compile(r"^(?:[AB]\d+[a-z]?|P-[AB])$")
ZH = "zh-tw"
DEX_RE = re.compile(r"^#?\s*0*(\d{1,4})$")
SET_RE = re.compile(r"^set:\s*(.+)$", re.IGNORECASE)


def image_url(base: str | None, quality: str = "low") -> str | None:
    """TCGdex dà la base dell'immagine: si aggiunge qualità e formato (low=245px, high=600px)."""
    return f"{base}/{quality}.webp" if base else None


def catalogs_for(lang_filter: str) -> list[str]:
    return {"en": ["en"], "ja": ["ja"], "zh": [ZH]}.get(lang_filter, ["en", "ja"])


def is_pocket(card: dict[str, Any]) -> bool:
    """Carte di Pokémon TCG Pocket (gioco solo digitale): set A1, A2a, B1, P-A…, immagini sotto /tcgp/."""
    return "/tcgp/" in (card.get("image") or "") or bool(POCKET_SET.match(card.get("id", "").rsplit("-", 1)[0]))


async def fill_missing_images(catalog: Catalog, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Le carte cinesi spesso non hanno la foto: usiamo quella giapponese (stesso set e numero, stessa carta)."""
    missing = {r["set_id"] for r in rows if r["catalog_lang"] == ZH and not r["image"]}
    if not missing:
        return rows
    sets = await asyncio.gather(*(catalog.get_set("ja", s) for s in missing))
    images = {c["id"]: c.get("image") for s in sets if s for c in s.get("cards") or []}
    for r in rows:
        if r["catalog_lang"] == ZH and not r["image"]:
            r["image"] = image_url(images.get(r["id"]))
    return rows


async def _set_index(catalog: Catalog, lang: str) -> dict[str, tuple[int, dict[str, Any]]]:
    """id set -> (posizione nell'elenco, set). L'elenco TCGdex è in ordine di uscita: più alto = più recente."""
    return {s["id"]: (i, s) for i, s in enumerate(await catalog.list_sets(lang))}


def summary(card: dict[str, Any], lang: str, set_info: dict[str, Any] | None) -> dict[str, Any]:
    set_id = card["id"].rsplit("-", 1)[0]
    total = ((set_info or {}).get("cardCount") or {}).get("official")
    return {
        "id": card["id"], "catalog_lang": lang, "name": card.get("name", ""), "number": card.get("localId", ""),
        "number_label": f"{card.get('localId', '')}/{total}" if total else card.get("localId", ""),
        "set_id": set_id, "set_name": (set_info or {}).get("name", set_id),
        "set_logo": _logo(set_info),
        "image": image_url(card.get("image")),
    }


def _logo(set_info: dict[str, Any] | None) -> str | None:
    logo = (set_info or {}).get("logo") or (set_info or {}).get("symbol")
    return f"{logo}.webp" if logo else None


async def _rank(catalog: Catalog, results: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Dal più recente al più vecchio, poi per numero; senza doppioni."""
    langs = {lang for lang, _ in results}
    indexes = dict(zip(langs, await asyncio.gather(*(_set_index(catalog, lang) for lang in langs))))
    seen, rows = set(), []
    for lang, card in results:
        key = (lang, card["id"])
        if key in seen or is_pocket(card):
            continue
        seen.add(key)
        pos, info = indexes[lang].get(card["id"].rsplit("-", 1)[0], (-1, None))
        rows.append((pos, normalize_number(card.get("localId")), summary(card, lang, info)))
    rows.sort(key=lambda r: (-r[0], r[1].zfill(6)))
    return await fill_missing_images(catalog, [r[2] for r in rows[:MAX_RESULTS]])


async def search(catalog: Catalog, matcher: CardMatcher, q: str, lang_filter: str = "all") -> list[dict[str, Any]]:
    q = q.strip()
    if not q:
        return []
    langs = catalogs_for(lang_filter)

    if m := DEX_RE.match(q):  # "#25", "#0025", "25"
        found = await asyncio.gather(*(catalog.search_cards(lang, {"dexId": f"eq:{int(m.group(1))}"})
                                       for lang in langs))
        return await _rank(catalog, [(lang, c) for lang, cards in zip(langs, found) for c in cards])

    if m := SET_RE.match(q):  # "set:151", "set:MEW", "set:sv03.5"
        return await _search_set(catalog, m.group(1).strip(), langs)

    query = parse_query(q)
    if query and query.is_specific:  # "30C 154", "Gengar ex 154/128"
        result = await matcher.match_text(query)
        wanted = [(ZH if ZH in langs and c.catalog_lang == "ja" else c.catalog_lang, c.card_id)
                  for c in result.candidates]  # le cinesi hanno gli stessi codici delle giapponesi
        cards = await asyncio.gather(*(catalog.get_card(lang, cid) for lang, cid in wanted))
        hits = [(lang, card) for (lang, _), card in zip(wanted, cards) if card and lang in langs + ["it"]]
        if hits:
            return await _rank(catalog, hits)

    if JAPANESE.search(q) and lang_filter == "all":
        # Ideogrammi: giapponese, e anche cinese se non ci sono kana (es. 耿鬼 = Gengar in cinese).
        langs = ["ja"] if KANA.search(q) else ["ja", ZH]
    name_langs = [lang for lang in langs if (lang != "en") == bool(JAPANESE.search(q))] or langs
    tasks = [catalog.search_cards(lang, {"name": q}) for lang in name_langs]
    tasks += [catalog.search_cards(lang, {"illustrator": q}) for lang in name_langs]
    found = await asyncio.gather(*tasks)
    pairs = [(name_langs[i % len(name_langs)], c) for i, cards in enumerate(found) for c in cards]
    return await _rank(catalog, pairs)


async def _search_set(catalog: Catalog, term: str, langs: list[str]) -> list[dict[str, Any]]:
    low = term.lower()
    for lang in langs:
        sets = await catalog.list_sets(lang)
        match = next((s for s in sets if s["id"].lower() == low), None)
        if match is None:
            by_code = await catalog.search_sets(lang, {"abbreviation.official": f"eq:{term.upper()}"})
            match = by_code[0] if by_code else None
        if match is None:
            match = next((s for s in sets if s.get("name", "").lower() == low), None) or \
                next((s for s in sets if low in s.get("name", "").lower()), None)
        if match:
            detail = await catalog.get_set(lang, match["id"])
            cards = [c for c in (detail or {}).get("cards") or [] if not is_pocket(c)]
            return await fill_missing_images(catalog, [summary(c, lang, detail) for c in cards][:400])
    return []
