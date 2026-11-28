"""Import di una lista incollata ("Carte che mi mancano · 30th Celebration" di Pullaxy)."""

import asyncio
from pathlib import Path

import pytest

from cardbot.collections.checklist import ChecklistError, ChecklistImporter, parse_checklist
from cardbot.db import Collection, CollectionItem
from tests.conftest import FakeCatalog
from tests.test_app_api import logged, make_client  # noqa: F401 (fixture)

TEXT = (Path(__file__).parent / "fixtures" / "pullaxy_30th_missing.txt").read_text(encoding="utf-8")


def test_parse_pullaxy_list():
    cl = parse_checklist(TEXT)
    assert cl.kind == "missing" and cl.set_name == "30th Celebration" and len(cl.rows) == 122
    by_line = {r.line: r for r in cl.rows}
    assert (by_line["BS 4 Charizard"].code, by_line["BS 4 Charizard"].number) == ("BS", "4")
    assert by_line["063s Mewtwo"].number == "063s" and by_line["R Mew"].number == "R"
    assert by_line["Basic Grass Energy"].number == "" and by_line["Basic Grass Energy"].name == "Basic Grass Energy"
    assert parse_checklist("Carte che ho · 30th Celebration\n#001 Exeggcute").kind == "owned"
    with pytest.raises(ChecklistError):
        parse_checklist("#001 Exeggcute")
    with pytest.raises(ChecklistError):
        parse_checklist("Carte che mi mancano · 30th Celebration\nniente")


def test_plan_matches_main_set_and_classic_reprints():
    plan = asyncio.run(ChecklistImporter(FakeCatalog()).plan(parse_checklist(TEXT)))
    assert [s["id"] for s in plan.sets] == ["30th", "30th-c"]
    got = {m.row.line: m.card["id"] for m in plan.matched}
    assert got["063s Mewtwo"] == "30th-063" and got["R Mew"] == "30th-R" and got["087 Nidoran"] == "30th-087"
    assert got["BS 4 Charizard"] == "30th-c-001" and got["BS 58 Pikachu"] == "30th-c-014"
    assert got["PRC 106 MGardevoir EX"] == "30th-c-023" and got["NVI 101 N"] == "30th-c-021"
    assert got["PL 47 Crobat [G] Lv.44"] == "30th-c-011"
    legend = [m.card["id"] for m in plan.matched if m.row.line.startswith("TM 100")]
    assert legend == ["30th-c-019", "30th-c-020"]       # le due metà della LEGEND
    review = [m.row.line for m in plan.matched if m.by_name]
    assert review == ["011 Genesect EX"]                # numero sbagliato: da verificare
    assert [r.line for r, _ in plan.unmatched] == ["Basic Grass Energy"]
    rest = {c["id"] for c, _ in plan.rest}
    assert len(plan.matched) + len(rest) == 161 + 30 and "30th-c-022" in rest and "30th-004" in rest


def test_import_wishes_missing_and_owns_the_rest(make_client):
    client, sessions = logged(make_client)
    pre = client.post("/api/collections/checklist/preview", json={"text": TEXT}).json()
    assert (pre["kind"], pre["set_name"], pre["listed"], pre["rest"]) == ("missing", "30th Celebration", 122, 69)
    assert pre["unmatched"][0]["line"] == "Basic Grass Energy" and pre["lang"] == "it"
    with sessions() as s:
        assert s.query(CollectionItem).count() == 0      # l'anteprima non salva nulla

    r = client.post("/api/collections/checklist", json={"text": TEXT, "lang": "it"}).json()
    assert (r["wished"], r["owned"], r["skipped"]) == (122, 69, 0)
    with sessions() as s:
        kinds = {}
        for i in s.query(CollectionItem).all():
            kinds.setdefault(i.collection.kind, set()).add((i.card_id, i.lang))
        assert ("30th-c-001", "any") in kinds["wishlist"] and ("30th-004", "it") in kinds["collection"]
        assert len(kinds["wishlist"]) == 122 and len(kinds["collection"]) == 69

    # Ripetere l'import non duplica nulla; una carta comprata esce dai desideri se la lista dice che ce l'hai.
    again = client.post("/api/collections/checklist", json={"text": TEXT}).json()
    assert (again["wished"], again["owned"], again["skipped"]) == (122, 0, 69)
    owned_list = "Carte che ho · 30th Celebration\n#BS 4 Charizard"
    r = client.post("/api/collections/checklist", json={"text": owned_list, "wish": False}).json()
    assert r["owned"] == 1
    with sessions() as s:
        wl = s.query(Collection).filter_by(kind="wishlist").one()
        assert "30th-c-001" not in {i.card_id for i in wl.items}


def test_import_errors(make_client):
    client, _ = logged(make_client)
    bad = client.post("/api/collections/checklist/preview", json={"text": "Carte che mi mancano · Boh Set\n#1 X"})
    assert bad.status_code == 422 and "non trovata" in bad.json()["detail"]
    assert client.post("/api/collections/checklist", json={"text": TEXT, "lang": "xx"}).status_code == 422
