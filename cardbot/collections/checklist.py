"""Import di una lista di carte incollata come testo (es. "Carte che mi mancano · 30th Celebration" di Pullaxy).

Formato atteso:
    Carte che mi mancano · 30th Celebration      <- tipo di lista e nome dell'espansione
    122 carte                                    <- ignorata
    #001 Exeggcute                               <- numero e nome
    #BS 4 Charizard                              <- ristampa: sigla del set originale, numero, nome
    #R Mew
Le ristampe (BS 4, TM 100…) in TCGdex stanno in un set collegato con un'altra numerazione (es. "30th-c"): si
cercano per nome lì. Nessuna carta viene inventata: quelle non trovate sono riportate.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from cardbot.catalog.base import Catalog
from cardbot.recognition.matcher import normalize_number

MAX_LINES = 2000
_CARD_LINE = re.compile(r"^#(?:(?P<code>[A-Za-z]{1,5})\s+(?P<onum>\d+[a-z]?)|(?P<num>[A-Za-z0-9\-]+))?\s+(?P<name>.+)$")


class ChecklistError(ValueError):
    pass


@dataclass
class ChecklistRow:
    line: str
    code: str | None     # sigla del set originale per le ristampe ("BS")
    number: str          # "001", "063s", "R", "" se assente
    name: str


@dataclass
class Checklist:
    kind: str            # "missing" (carte che mi mancano) o "owned" (carte che ho)
    set_name: str
    rows: list[ChecklistRow]


@dataclass
class ChecklistMatch:
    row: ChecklistRow
    card: dict[str, Any]
    set_id: str
    set_name: str
    by_name: bool        # il numero non tornava: abbinata per nome


@dataclass
class ChecklistPlan:
    checklist: Checklist
    sets: list[dict[str, Any]]                     # set principale e set collegati usati
    matched: list[ChecklistMatch] = field(default_factory=list)
    unmatched: list[tuple[ChecklistRow, str]] = field(default_factory=list)
    rest: list[tuple[dict[str, Any], dict[str, Any]]] = field(default_factory=list)  # (carta, set) non in lista


def parse_checklist(text: str) -> Checklist:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()][:MAX_LINES]
    header = next((ln for ln in lines if not ln.startswith("#")), "")
    parts = re.split(r"\s+[·•|–-]\s+", header, maxsplit=1)
    if len(parts) != 2 or not parts[1].strip():
        raise ChecklistError("Nella prima riga non trovo l'espansione (es. «Carte che mi mancano · 30th Celebration»).")
    title = _simplify(parts[0])
    kind = "owned" if re.search(r"\b(ho|possiedo|posseduta|posseduto|possedute|owned|have)\b", title) \
        and "manc" not in title else "missing"
    rows = []
    for ln in lines:
        if not ln.startswith("#"):
            continue
        m = _CARD_LINE.match(ln)
        if not m:
            continue
        code = m.group("code")
        number = m.group("onum") if code else (m.group("num") or "")
        rows.append(ChecklistRow(line=ln.lstrip("#").strip(), code=code.upper() if code else None,
                                 number=number, name=m.group("name").strip()))
    if not rows:
        raise ChecklistError("Non trovo carte nella lista: ogni carta deve stare su una riga che inizia con #.")
    return Checklist(kind=kind, set_name=parts[1].strip(), rows=rows)


def _simplify(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tier(wanted: str, got: str) -> int:
    """Quanto il nome della lista somiglia a quello del catalogo: 3 uguale, 2 parole contenute, 1 simile, 0 no."""
    if not wanted or not got:
        return 0
    if wanted == got or wanted.replace(" ", "") == got.replace(" ", ""):
        return 3
    w, g = set(wanted.split()), set(got.split())
    if g <= w or w <= g:
        return 2
    return 1 if fuzz.ratio(wanted, got) >= 85 else 0


class ChecklistImporter:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    async def plan(self, checklist: Checklist) -> ChecklistPlan:
        main, check_names = await self._find_set(checklist.set_name)
        if main is None:
            raise ChecklistError(f"Espansione «{checklist.set_name}» non trovata nel catalogo.")
        related = []
        for s in await self._catalog.list_sets("en"):
            if s["id"].lower().startswith(main["id"].lower() + "-"):
                detail = await self._catalog.get_set("en", s["id"])
                if detail:
                    related.append(detail)
        plan = ChecklistPlan(checklist=checklist, sets=[main])
        taken: set[str] = set()
        for row in checklist.rows:
            found, by_name, reason = self._match(row, main, related, check_names)
            if not found:
                plan.unmatched.append((row, reason))
                continue
            for card, s in found:
                if card["id"] in taken:
                    continue
                taken.add(card["id"])
                plan.matched.append(ChecklistMatch(row=row, card=card, set_id=s["id"], set_name=s.get("name", s["id"]),
                                                   by_name=by_name))
        # I set collegati contano solo se la lista ne usa almeno una carta (altrimenti non fanno parte della lista).
        used = {m.set_id for m in plan.matched}
        plan.sets += [s for s in related if s["id"] in used]
        for s in plan.sets:
            plan.rest += [(c, s) for c in s.get("cards") or [] if c["id"] not in taken]
        return plan

    async def _find_set(self, name: str) -> tuple[dict[str, Any] | None, bool]:
        """Set per nome inglese; se il nome è italiano si usa lo stesso codice senza controllare i nomi delle carte."""
        wanted = _simplify(name)
        for lang in ("en", "it"):
            sets = await self._catalog.list_sets(lang)
            hit = [s for s in sets if _simplify(s.get("name", "")) == wanted]
            if not hit:
                scored = sorted(((fuzz.ratio(wanted, _simplify(s.get("name", ""))), s) for s in sets),
                                key=lambda x: x[0], reverse=True)
                hit = [scored[0][1]] if scored and scored[0][0] >= 92 else []
            if hit:
                detail = await self._catalog.get_set("en", hit[-1]["id"])
                if detail:
                    return detail, lang == "en"
        return None, True

    def _match(self, row: ChecklistRow, main: dict[str, Any], related: list[dict[str, Any]],
               check_names: bool) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], bool, str]:
        wanted = _simplify(row.name)
        if row.number and not row.code:
            numbers = {normalize_number(row.number), normalize_number(re.sub(r"[a-z]+$", "", row.number))}
            same = [c for c in main.get("cards") or [] if normalize_number(str(c.get("localId", ""))) in numbers]
            good = [c for c in same if not check_names or _tier(wanted, _simplify(c.get("name", "")))]
            if good:
                return [(good[0], main)], False, ""
        # Ristampa (sigla del set originale) o numero che non torna: per nome, prima nei set collegati.
        pools = related + [main] if row.code else [main] + related
        for s in pools:
            scored = [(_tier(wanted, _simplify(c.get("name", ""))), c) for c in s.get("cards") or []]
            best = max((t for t, _ in scored), default=0)
            if best == 0:
                continue
            top = [c for t, c in scored if t == best]
            review = not row.code   # con la sigla del set originale l'abbinamento per nome è quello previsto
            if len(top) == 1:
                return [(top[0], s)], review, ""
            if "legend" in wanted.split() and best == 3:   # le LEGEND sono due carte (parte alta e bassa)
                return [(c, s) for c in top], review, ""
            return [], False, f"più carte con questo nome in {s.get('name')}"
        return [], False, "non c'è nel catalogo dell'espansione"
