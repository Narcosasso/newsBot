import pytest

from cardbot.recognition.matcher import CardMatcher, name_similarity, normalize_number
from cardbot.recognition.vision import VisionResult
from cardbot.variants import choose_variant


def vision(**kw) -> VisionResult:
    base = dict(is_pokemon_card=True, language="en", confidence=0.95)
    base.update(kw)
    return VisionResult(**base)


@pytest.mark.parametrize("raw,expected", [
    ("006", "6"), ("006/165", "6"), ("TG05", "TG5"), ("SV-P 045", "SVP45"), ("100", "100"), ("0", "0"),
])
def test_normalize_number(raw, expected):
    assert normalize_number(raw) == expected


def test_name_similarity_handles_dashes_and_case():
    assert name_similarity("Charizard-ex", "Charizard ex") > 0.95
    assert name_similarity("Pikachu", "Charizard ex") < 0.6


async def test_english_card_with_set_code_is_confident(catalog):
    r = await CardMatcher(catalog).match(vision(name="Charizard ex", set_code="MEW", number="006", set_total="165"))
    assert r.confident
    assert r.best.card_id == "sv03.5-006"
    assert r.best.variants == ["holo"]


async def test_set_found_by_total_when_code_missing(catalog):
    r = await CardMatcher(catalog).match(vision(name="Charizard ex", number="006", set_total="165"))
    assert r.best.card_id == "sv03.5-006"
    # Senza codice set il punteggio è più basso ma resta il migliore.
    assert r.best.score < 0.9


async def test_italian_card_uses_italian_catalog(catalog):
    r = await CardMatcher(catalog).match(
        vision(language="it", name="Charizard-ex", set_code="MEW", number="006", set_total="165"))
    assert r.confident
    assert r.best.card_id == "sv03.5-006" and r.best.catalog_lang == "it"


async def test_japanese_card_matches_by_set_id(catalog):
    r = await CardMatcher(catalog).match(
        vision(language="ja", name="リザードンex", set_code="SV2a", number="006", set_total="165"))
    assert r.confident
    assert r.best.card_id == "SV2a-006" and r.best.catalog_lang == "ja"


async def test_korean_card_is_searched_in_japanese_catalog_with_warning(catalog):
    r = await CardMatcher(catalog).match(
        vision(language="ko", name="리자몽ex", set_code="SV2a", number="006", set_total="165"))
    assert r.best.card_id == "SV2a-006"
    assert r.warnings and "coreana" in r.warnings[0]


async def test_name_only_gives_candidates_not_confident(catalog):
    r = await CardMatcher(catalog).match(vision(name="Charizard ex"))
    assert not r.confident
    assert 1 < len(r.candidates) <= 3
    assert all("Charizard" in c.name for c in r.candidates)


async def test_low_vision_confidence_is_not_confident(catalog):
    r = await CardMatcher(catalog).match(
        vision(name="Charizard ex", set_code="MEW", number="006", set_total="165", confidence=0.3))
    assert r.best.card_id == "sv03.5-006" and not r.confident


async def test_wrong_name_lowers_score(catalog):
    r = await CardMatcher(catalog).match(vision(name="Pikachu", set_code="MEW", number="006", set_total="165"))
    good = await CardMatcher(catalog).match(
        vision(name="Charizard ex", set_code="MEW", number="006", set_total="165"))
    assert r.best.score < good.best.score


async def test_no_match(catalog):
    r = await CardMatcher(catalog).match(vision(name=None, set_code="ZZZ", number="999", set_total="999"))
    assert r.candidates == [] and not r.confident


@pytest.mark.parametrize("available,hint,expected", [
    (["holo"], "unknown", "holo"),
    (["normal", "reverse"], "reverse", "reverse"),
    (["normal", "reverse"], "unknown", None),
    (["normal", "reverse"], "holo", None),
    ([], "unknown", "normal"),
])
def test_choose_variant(available, hint, expected):
    assert choose_variant(available, hint) == expected
