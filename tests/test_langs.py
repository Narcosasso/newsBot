from cardbot.langs import format_langs, parse_langs


def test_basic_list():
    r = parse_langs("ita, eng, jap")
    assert r.ok and r.langs == ["it", "en", "ja"]


def test_aliases_and_case():
    assert parse_langs("Italiano Inglese GIAPPONESE coreano").langs == ["it", "en", "ja", "ko"]
    assert parse_langs("it/en/jp/kr").langs == ["it", "en", "ja", "ko"]


def test_separators_and_conjunction():
    assert parse_langs("ita e eng; jap + de").langs == ["it", "en", "ja", "de"]


def test_dedup_keeps_order():
    assert parse_langs("eng, ita, english, it").langs == ["en", "it"]


def test_unknown_tokens_reported():
    r = parse_langs("ita, klingon")
    assert r.langs == ["it"] and r.unknown == ["klingon"] and not r.ok


def test_empty():
    r = parse_langs("   ")
    assert not r.ok and r.langs == [] and r.unknown == []


def test_punctuation_is_ignored():
    assert parse_langs("ita, eng!").langs == ["it", "en"]


def test_format_langs():
    assert format_langs(["it", "ja"]) == "ita, jap"
