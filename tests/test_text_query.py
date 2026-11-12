import pytest

from cardbot.recognition.matcher import CardMatcher
from cardbot.recognition.text_query import parse_query


@pytest.mark.parametrize("text,code,number,total,name", [
    ("MEW 006", "MEW", "006", None, None),
    ("MEW 006/165", "MEW", "006", "165", None),
    ("006/165 MEW", "MEW", "006", "165", None),
    ("SV2a 006/165", "SV2a", "006", "165", None),
    ("sv03.5 6", "sv03.5", "6", None, None),
    ("Charizard ex MEW 006", "MEW", "006", None, "Charizard ex"),
    ("Charizard ex 006/165", None, "006", "165", "Charizard ex"),
    ("PAL TG05", "PAL", "TG05", None, None),
    ("Pikachu", None, None, None, "Pikachu"),
])
def test_parse_query(text, code, number, total, name):
    q = parse_query(text)
    assert (q.set_code, q.number, q.set_total, q.name) == (code, number, total, name)


def test_langs_and_variant_in_query():
    q = parse_query("MEW 001 reverse ita, JAP")
    assert q.set_code == "MEW" and q.number == "001"
    assert q.variant == "reverse" and q.langs == ["it", "ja"]


def test_only_langs_is_not_a_query():
    assert parse_query("ita, eng") is None


def test_is_specific():
    assert parse_query("MEW 006").is_specific
    assert not parse_query("2").is_specific
    assert not parse_query("Pikachu").is_specific


async def test_match_text_set_code_and_number_is_confident(catalog):
    r = await CardMatcher(catalog).match_text(parse_query("MEW 006"))
    assert r.confident and r.best.card_id == "sv03.5-006"


async def test_match_text_lowercase_code(catalog):
    r = await CardMatcher(catalog).match_text(parse_query("mew 006"))
    assert r.confident and r.best.card_id == "sv03.5-006"


async def test_match_text_japanese_set(catalog):
    r = await CardMatcher(catalog).match_text(parse_query("SV2a 006/165"))
    assert r.confident and r.best.card_id == "SV2a-006" and r.best.catalog_lang == "ja"


async def test_match_text_name_and_number_without_code(catalog):
    r = await CardMatcher(catalog).match_text(parse_query("Charizard ex 006/165"))
    assert r.best.card_id == "sv03.5-006"


async def test_match_text_name_only_gives_candidates(catalog):
    r = await CardMatcher(catalog).match_text(parse_query("Charizard ex"))
    assert not r.confident and len(r.candidates) > 1


async def test_match_text_unknown(catalog):
    r = await CardMatcher(catalog).match_text(parse_query("ZZZ 999"))
    assert r.candidates == []
