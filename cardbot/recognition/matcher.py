"""Match tra i dati letti dalla foto e il catalogo TCGdex.

Punteggio di ogni candidato (0..1):
  numero di collezione uguale   +0.45
  codice set uguale              +0.30  (oppure solo totale del set uguale +0.15)
  somiglianza del nome           +0.25 * similarità
Il match è "sicuro" se il migliore supera MIN_SCORE, stacca il secondo di almeno MIN_GAP
e la lettura della foto ha confidenza sufficiente; altrimenti si propongono fino a 3 candidati.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from cardbot.catalog.base import Catalog, catalog_lang_for
from cardbot.recognition.text_query import TextQuery
from cardbot.recognition.vision import VisionResult
from cardbot.variants import variants_of

MIN_SCORE = 0.80
MIN_GAP = 0.15
MIN_VISION_CONFIDENCE = 0.6
MAX_CANDIDATES = 3

W_NUMBER = 0.45
W_SET = 0.30
W_TOTAL = 0.15
W_NAME = 0.25


@dataclass
class Candidate:
    card_id: str
    catalog_lang: str
    name: str
    set_id: str
    set_name: str
    local_id: str
    set_official: int | None
    score: float
    variants: list[str] = field(default_factory=list)

    def short(self) -> str:
        total = f"/{self.set_official}" if self.set_official else ""
        return f"{self.name} · {self.set_name} {self.local_id}{total}"


@dataclass
class MatchResult:
    candidates: list[Candidate]
    confident: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def best(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None


def normalize_number(value: str | None) -> str:
    """'006' -> '6', 'TG05' -> 'TG5', 'SV-P 045' -> 'SVP45'."""
    if not value:
        return ""
    v = re.sub(r"[\s\-_.]", "", value.upper())
    v = v.split("/")[0]
    return re.sub(r"(?<![0-9])0+(?=[0-9])", "", v)


def normalize_name(value: str | None) -> str:
    if not value:
        return ""
    v = unicodedata.normalize("NFKC", value).lower()
    v = re.sub(r"[-'’.·:]", " ", v)
    return re.sub(r"\s+", " ", v).strip()


def name_similarity(a: str | None, b: str | None) -> float:
    a, b = normalize_name(a), normalize_name(b)
    if not a or not b:
        return 0.0
    return fuzz.WRatio(a, b) / 100.0


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _set_matches_code(set_obj: dict[str, Any], code: str) -> bool:
    code_n = code.strip().lower().replace(" ", "")
    if set_obj.get("id", "").lower() == code_n:
        return True
    abbr = (set_obj.get("abbreviation") or {})
    return any(str(v).lower() == code_n for v in abbr.values() if v)


class CardMatcher:
    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog

    async def match(self, vision: VisionResult) -> MatchResult:
        warnings: list[str] = []
        if vision.language == "ko":
            warnings.append(
                "Carta coreana: la cerco nel catalogo giapponese (stessi set e numeri), verifica il risultato."
            )
        lang = catalog_lang_for(vision.language if vision.language != "other" else "en")

        candidates: dict[str, Candidate] = {}
        number = normalize_number(vision.number)
        code_matched = False
        if number:
            sets = await self._candidate_sets(lang, vision)
            code_matched = any(score == W_SET for _, score in sets)
            for set_obj, set_score in sets:
                for card in set_obj.get("cards") or []:
                    if normalize_number(card.get("localId")) == number:
                        cand = self._candidate(card, set_obj, lang, vision, set_score + W_NUMBER)
                        _keep_best(candidates, cand)

        if not candidates and vision.name:
            for cand in await self._by_name(lang, vision):
                _keep_best(candidates, cand)

        ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)[:MAX_CANDIDATES]
        await self._attach_variants(ranked)
        confident = bool(ranked) and ranked[0].score >= MIN_SCORE and vision.confidence >= MIN_VISION_CONFIDENCE
        if confident and len(ranked) > 1 and ranked[0].score - ranked[1].score < MIN_GAP:
            confident = False
        if vision.set_code and not code_matched and not vision.name:
            # Codice set indicato ma inesistente in questo catalogo: il solo totale non basta per essere sicuri.
            confident = False
        return MatchResult(candidates=ranked, confident=confident, warnings=warnings)

    async def _candidate_sets(self, lang: str, vision: VisionResult) -> list[tuple[dict[str, Any], float]]:
        sets = await self._catalog.list_sets(lang)
        total = _to_int(vision.set_total)
        code = (vision.set_code or "").strip()

        by_code = [s for s in sets if code and _set_matches_code(s, code)]
        if code and not by_code:
            # Sigle come "MEW" o "PAL" non sono nell'elenco dei set: le cerca l'API con un filtro esatto.
            by_code = await self._catalog.search_sets(lang, {"abbreviation.official": f"eq:{code.upper()}"})
        if by_code:
            details = await asyncio.gather(*(self._catalog.get_set(lang, s["id"]) for s in by_code))
            return [(d, W_SET) for d in details if d]

        by_total = [s for s in sets if total and _to_int((s.get("cardCount") or {}).get("official")) == total]
        # Il codice set (es. "MEW") è solo nel dettaglio del set: lo controlliamo lì.
        details = await asyncio.gather(*(self._catalog.get_set(lang, s["id"]) for s in by_total[:25]))
        out = []
        for d in details:
            if not d:
                continue
            out.append((d, W_SET if code and _set_matches_code(d, code) else W_TOTAL))
        return out

    async def _by_name(self, lang: str, vision: VisionResult) -> list[Candidate]:
        results = await self._catalog.search_cards(lang, {"name": vision.name or ""})
        number = normalize_number(vision.number)
        out = []
        for card in results[:50]:
            score = W_NAME * name_similarity(vision.name, card.get("name"))
            if number and normalize_number(card.get("localId")) == number:
                score += W_NUMBER
            out.append(Candidate(
                card_id=card["id"], catalog_lang=lang, name=card.get("name", ""),
                set_id=card["id"].rsplit("-", 1)[0], set_name=card["id"].rsplit("-", 1)[0],
                local_id=card.get("localId", ""), set_official=None, score=round(score, 4),
            ))
        return out

    async def match_text(self, query: TextQuery) -> MatchResult:
        """Ricerca testuale: prova il catalogo internazionale e poi quello giapponese."""
        code = query.set_code
        name = query.name
        # "mew 006": una parola sola di poche lettere può essere la sigla del set scritta in minuscolo.
        if not code and name and re.fullmatch(r"[A-Za-z]{2,5}", name) and query.number:
            code, name = name.upper(), None
        merged: dict[str, Candidate] = {}
        warnings: list[str] = []
        for lang in ("en", "ja"):
            vision = VisionResult(
                is_pokemon_card=True, language=lang, name=name, set_code=code, number=query.number,
                set_total=query.set_total, confidence=0.9 if code and query.number else 0.7,
            )
            result = await self.match(vision)
            if not result.candidates and code and name is None and query.name:
                # La parola non era una sigla: riprova come nome.
                result = await self.match(vision.model_copy(update={"set_code": None, "name": query.name}))
            for cand in result.candidates:
                _keep_best(merged, cand)
            if result.confident:
                return result
        ranked = sorted(merged.values(), key=lambda c: c.score, reverse=True)[:MAX_CANDIDATES]
        confident = len(ranked) == 1 and ranked[0].score >= MIN_SCORE
        return MatchResult(candidates=ranked, confident=confident, warnings=warnings)

    def _candidate(self, card: dict[str, Any], set_obj: dict[str, Any], lang: str,
                   vision: VisionResult, base: float) -> Candidate:
        if vision.name:
            score = base + W_NAME * name_similarity(vision.name, card.get("name"))
        else:
            # Ricerca solo per set + numero (es. testo "MEW 006"): il nome non entra nel punteggio.
            score = base / (1 - W_NAME)
        return Candidate(
            card_id=card["id"], catalog_lang=lang, name=card.get("name", ""),
            set_id=set_obj.get("id", ""), set_name=set_obj.get("name", ""),
            local_id=card.get("localId", ""),
            set_official=_to_int((set_obj.get("cardCount") or {}).get("official")),
            score=round(min(score, 1.0), 4),
        )

    async def _attach_variants(self, candidates: list[Candidate]) -> None:
        cards = await asyncio.gather(*(self._catalog.get_card(c.catalog_lang, c.card_id) for c in candidates))
        for cand, card in zip(candidates, cards):
            if card:
                cand.variants = variants_of(card)
                if cand.set_official is None:
                    s = card.get("set") or {}
                    cand.set_name = s.get("name", cand.set_name)
                    cand.set_official = _to_int((s.get("cardCount") or {}).get("official"))


def _keep_best(store: dict[str, Candidate], cand: Candidate) -> None:
    prev = store.get(cand.card_id)
    if prev is None or cand.score > prev.score:
        store[cand.card_id] = cand
