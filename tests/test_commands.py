import pytest

from cardbot.bot.commands import parse_command


def test_not_a_command():
    assert parse_command("MEW 006") is None
    assert parse_command("Charizard ex") is None
    assert parse_command("stop pikachu") is None


@pytest.mark.parametrize("text", ["lista", "Lista", "elenco", " carte "])
def test_list(text):
    assert parse_command(text).kind == "list"


def test_help():
    assert parse_command("aiuto").kind == "help"


def test_stop():
    assert parse_command("stop 2").index == 2
    assert parse_command("stop tutte").all
    assert parse_command("stop").kind == "error"


def test_langs_with_index():
    c = parse_command("lingue 2 ita, jap")
    assert (c.kind, c.index, c.langs) == ("langs", 2, ["it", "ja"])


def test_langs_without_index_and_bare():
    c = parse_command("lingue ita eng")
    assert c.kind == "langs" and c.index is None and c.langs == ["it", "en"]
    assert parse_command("lingue").kind == "supported_langs"
    assert parse_command("lingue 1 klingon").kind == "error"


@pytest.mark.parametrize("text,pct,eur,set_pct,set_eur", [
    ("soglia 15%", 15.0, None, True, False),
    ("soglia 15 %", 15.0, None, True, False),
    ("soglia 2€", None, 2.0, False, True),
    ("soglia 2,5 €", None, 2.5, False, True),
    ("soglia €3", None, 3.0, False, True),
    ("soglia 1.5 euro", None, 1.5, False, True),
    ("soglia 15% 2€", 15.0, 2.0, True, True),
    ("soglia 0% 2€", None, 2.0, True, True),   # 0 disattiva la percentuale
])
def test_global_threshold(text, pct, eur, set_pct, set_eur):
    c = parse_command(text)
    assert c.kind == "threshold" and c.index is None
    assert (c.pct, c.eur, c.set_pct, c.set_eur) == (pct, eur, set_pct, set_eur)


def test_per_card_threshold_and_reset():
    c = parse_command("soglia 3 20%")
    assert c.index == 3 and c.pct == 20.0 and not c.set_eur
    r = parse_command("soglia 3 predefinita")
    assert r.index == 3 and r.reset


def test_threshold_show_and_errors():
    assert parse_command("soglia").kind == "threshold_show"
    assert parse_command("soglia 2").kind == "error"
    assert parse_command("soglia tanta").kind == "error"
    assert parse_command("soglia predefinita").kind == "error"
    assert parse_command("soglia 5000%").kind == "error"
