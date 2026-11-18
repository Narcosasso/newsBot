"""Espansioni, Pokédex e carte possedute nei risultati di ricerca."""

from tests.test_app_api import logged, make_client  # noqa: F401 (fixture)


def _own(client, card_id="sv03.5-006", qty=2):
    r = client.put("/api/collection-items", json={"card_id": card_id, "catalog_lang": "en", "variant": "holo",
                                                  "lang": "it", "quantity": qty})
    assert r.status_code == 200


def test_sets_grouped_by_series_without_pocket(make_client):
    client, _ = logged(make_client)
    _own(client)
    r = client.get("/api/sets", params={"lang": "en"}).json()
    ids = [s["id"] for s in r["series"]]
    assert "tcgp" not in ids and ids[-1] == "misc" and ids[0] == "sv"
    sv = r["series"][0]["sets"]
    assert sv[0]["id"] != "svp" and sv[-1]["id"] == "svp"          # dal più recente
    mew = [s for s in sv if s["id"] == "sv03.5"][0]
    assert mew["owned"] == 1 and mew["total"] and r["owned_sets"] == 1


def test_set_detail_marks_owned_cards(make_client):
    client, _ = logged(make_client)
    _own(client)
    d = client.get("/api/sets/en/sv03.5").json()
    assert d["owned_unique"] == 1 and d["owned_cards"] == 2 and d["owned_value"] == 16.26
    owned = [c for c in d["cards"] if c["owned"]]
    assert [c["id"] for c in owned] == ["sv03.5-006"] and len(d["cards"]) > 150
    assert client.get("/api/sets/en/nope").status_code == 404


def test_pokedex_counts_owned_species(make_client):
    client, _ = logged(make_client)
    _own(client)
    d = client.get("/api/pokedex").json()
    assert d["total"] == 1025 and d["pokemon"][0][:3] == [1, "Bulbasaur", 1]
    charizard = d["pokemon"][5]
    assert charizard[1] == "Charizard" and charizard[3] == 2 and d["owned_species"] == 1


def test_search_shows_owned_quantity(make_client):
    client, _ = logged(make_client)
    _own(client)
    cards = client.get("/api/search", params={"q": "Charizard ex", "lang": "en"}).json()["cards"]
    assert {c["id"]: c["owned"] for c in cards}["sv03.5-006"] == 2
