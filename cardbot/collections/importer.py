"""Import di una collezione esportata da un'altra app (formato JSON di MyDex, "schemaVersion": 1).

Ogni carta del file ha il codice set e il numero del catalogo usato dall'altra app (es. "me2pt5" e "4"), che non
coincidono sempre con TCGdex (lì "me02.5" e "004"). L'abbinamento procede così:
1. set: codice normalizzato (me2pt5 -> me02.5, sv1 -> sv01, m5_ja -> M5 giapponese) o alias noti, poi nome del set;
2. carta: stesso numero nel set (e nome compatibile); se il numero non torna, nome unico nel set ("da verificare").
Le carte non abbinate vengono riportate all'utente, mai inventate.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from cardbot.catalog.base import Catalog
from cardbot.recognition.matcher import normalize_number

# Codici dell'altra app che non si ricavano con le regole generali.
SET_ALIASES = {"me55": "30th", "me55c": "30th-c", "mcd22": "2022swsh", "mcd21": "2021swsh"}

LANG_CODES = {"EN": "en", "IT": "it", "DE": "de", "FR": "fr", "ES": "es", "PT": "pt", "JA": "ja", "JP": "ja",
              "KO": "ko", "KR": "ko", "ZH": "zh", "CN": "zh"}
VARIANT_NAMES = {"normal": "normal", "non holo": "normal", "holo": "holo", "holofoil": "holo",
                 "reverse holo": "reverse", "reverse holofoil": "reverse", "reverse": "reverse"}


@dataclass
class ImportRow:
    """Una carta del file (per variante): cosa dice il file, prima dell'abbinamento."""

    source_id: str
    name: str
    number: str
    set_code: str
    set_name: str
    lang: str          # lingua di stampa (it, en, ja…)
    variant_name: str  # come la chiama il file ("Holo", "Anniversary Stamp"…)
    quantity: int
    image: str | None = None  # foto indicata dal file: si usa solo se il catalogo non ne ha una


@dataclass
class MatchedRow:
    row: ImportRow
    catalog_lang: str
    card_id: str
    set_id: str
    set_name: str
    name: str
    variant: str             # normal / holo / reverse (corretta poi sui dati della carta, se serve)
    needs_review: bool       # abbinata per nome e non per numero


@dataclass
class ImportPlan:
    collection_name: str
    matched: list[MatchedRow] = field(default_factory=list)
    unmatched: list[tuple[ImportRow, str]] = field(default_factory=list)  # (riga, motivo)


class ImportFormatError(ValueError):
    pass


def parse_export(data: Any) -> tuple[str, list[ImportRow]]:
    """Legge il JSON esportato. Errore chiaro se non è il formato atteso."""
    if not isinstance(data, dict) or not isinstance(data.get("cards"), list):
        raise ImportFormatError("Il file non contiene un elenco di carte (campo \"cards\").")
    rows: list[ImportRow] = []
    for c in data["cards"]:
        if not isinstance(c, dict) or not c.get("setID") or not c.get("number"):
            continue
        lang = LANG_CODES.get(str(c.get("language") or "EN").upper(), "en")
        base = dict(source_id=str(c.get("id") or ""), name=str(c.get("name") or ""), number=str(c["number"]),
                    set_code=str(c["setID"]), set_name=str(c.get("setName") or ""), lang=lang,
                    image=_https(c.get("imageURL")))
        variants = [v for v in c.get("variants") or [] if isinstance(v, dict) and int(v.get("quantity") or 0) > 0]
        if variants:
            rows += [ImportRow(**base, variant_name=str(v.get("name") or "Normal"), quantity=int(v["quantity"]))
                     for v in variants]
        elif int(c.get("quantity") or 0) > 0:
            rows.append(ImportRow(**base, variant_name="Normal", quantity=int(c["quantity"])))
    if not rows:
        raise ImportFormatError("Nessuna carta trovata nel file.")
    name = str(data.get("collectionName") or "Collezione importata")[:100]
    return name, rows


def _https(url: object) -> str | None:
    return url[:300] if isinstance(url, str) and url.startswith("https://") else None


def catalog_for(lang: str) -> str:
    return {"ja": "ja", "ko": "ja", "zh": "zh-tw"}.get(lang, "en")


def set_id_candidates(code: str, catalog_lang: str) -> list[str]:
    """Possibili codici TCGdex per il codice set dell'altra app."""
    base = re.sub(r"_(ja|jp|kr|ko|zh)$", "", code.strip(), flags=re.IGNORECASE)
    out = [SET_ALIASES.get(base.lower(), base)]
    norm = base.lower().replace("pt", ".")              # me2pt5 -> me2.5
    if m := re.match(r"^([a-z]+)(\d+)(\.5)?$", norm):    # me2.5 -> me02.5, sv1 -> sv01
        out.append(f"{m.group(1)}{int(m.group(2)):02d}{m.group(3) or ''}")
    out.append(norm)
    if catalog_lang != "en":                            # i set giapponesi in TCGdex sono maiuscoli (M5, SV2a)
        out += [x.upper() for x in out] + [x[:1].upper() + x[1:] for x in out]
    seen: list[str] = []
    return [x for x in out if x and not (x in seen or seen.append(x))]


def _simplify(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class CollectionImporter:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._sets: dict[tuple[str, str], dict[str, Any] | None] = {}

    async def plan(self, collection_name: str, rows: list[ImportRow]) -> ImportPlan:
        plan = ImportPlan(collection_name=collection_name)
        for row in rows:
            catalog_lang = catalog_for(row.lang)
            set_detail = await self._resolve_set(catalog_lang, row.set_code, row.set_name)
            if set_detail is None:
                plan.unmatched.append((row, f"set «{row.set_name or row.set_code}» non trovato nel catalogo"))
                continue
            card, by_name = self._match_card(set_detail, row, check_name=row.lang in ("en", "ja", "zh"))
            if card is None:
                plan.unmatched.append((row, f"carta n. {row.number} non trovata in {set_detail.get('name')}"))
                continue
            plan.matched.append(MatchedRow(
                row=row, catalog_lang=catalog_lang, card_id=card["id"], set_id=set_detail["id"],
                set_name=set_detail.get("name", set_detail["id"]), name=card.get("name") or row.name,
                variant=VARIANT_NAMES.get(row.variant_name.strip().lower(), "holo"), needs_review=by_name))
        return plan

    async def _resolve_set(self, catalog_lang: str, code: str, name: str) -> dict[str, Any] | None:
        key = (catalog_lang, code)
        if key not in self._sets:
            self._sets[key] = await self._find_set(catalog_lang, code, name)
        return self._sets[key]

    async def _find_set(self, catalog_lang: str, code: str, name: str) -> dict[str, Any] | None:
        sets = await self._catalog.list_sets(catalog_lang)
        by_id = {s["id"].lower(): s for s in sets}
        for cand in set_id_candidates(code, catalog_lang):
            if cand.lower() in by_id:
                return await self._catalog.get_set(catalog_lang, by_id[cand.lower()]["id"])
        if name:
            wanted = _simplify(name)
            exact = [s for s in sets if _simplify(s.get("name", "")) == wanted]
            if exact:
                return await self._catalog.get_set(catalog_lang, exact[-1]["id"])
            scored = sorted(((fuzz.token_set_ratio(wanted, _simplify(s.get("name", ""))),
                              fuzz.ratio(wanted, _simplify(s.get("name", ""))), s) for s in sets),
                            key=lambda x: (x[0], x[1]), reverse=True)
            if scored and scored[0][0] >= 90:
                return await self._catalog.get_set(catalog_lang, scored[0][2]["id"])
        return None

    @staticmethod
    def _match_card(set_detail: dict[str, Any], row: ImportRow,
                    check_name: bool) -> tuple[dict[str, Any] | None, bool]:
        cards = set_detail.get("cards") or []
        number = normalize_number(row.number)
        wanted = _simplify(row.name)

        def similar(card: dict[str, Any]) -> bool:
            got = _simplify(card.get("name", ""))
            return not check_name or not wanted or wanted in got or got in wanted or fuzz.ratio(wanted, got) >= 70

        same_number = [c for c in cards if normalize_number(str(c.get("localId", ""))) == number]
        good = [c for c in same_number if similar(c)]
        if good:
            return good[0], False
        # Numero diverso (ristampe con un'altra numerazione): nome unico nel set, da far verificare.
        if wanted:
            by_name = [c for c in cards if _simplify(c.get("name", "")) and
                       (_simplify(c.get("name", "")) in wanted or wanted in _simplify(c.get("name", "")))]
            if len(by_name) == 1:
                return by_name[0], True
        if same_number and not check_name:
            return same_number[0], False
        return None, False
