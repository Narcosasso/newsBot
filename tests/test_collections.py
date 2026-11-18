"""Collezioni: lettura del file esportato, abbinamento al catalogo, valore, API e aggiornamento notturno."""

import json
from datetime import date

import pytest

from cardbot.collections.importer import (
    CollectionImporter, ImportFormatError, parse_export, set_id_candidates,
)
from cardbot.collections.service import apply_plan, refresh_items, update_from_price_guide
from cardbot.db import (
    Collection, CollectionItem, CollectionValue, PriceHistory, get_or_create_user, make_engine,
    make_session_factory,
)
from tests.test_app_api import logged, make_client  # noqa: F401 (fixture)


def card(set_id, set_name, number, name, lang="EN", variants=(("Holo", 1),), image=None):
    return {"id": f"{set_id}-{number}", "setID": set_id, "setName": set_name, "number": number, "name": name,
            "language": lang, "quantity": sum(q for _, q in variants), "imageURL": image,
            "variants": [{"name": v, "quantity": q, "key": f"k{i}"} for i, (v, q) in enumerate(variants)]}


EXPORT = {
    "collectionName": "le mie carte", "schemaVersion": 1,
    "cards": [
        card("sv3pt5", "151", "6", "Charizard ex", variants=(("Holo", 2),)),
        card("sv2a_ja", "ポケモンカード151", "185", "リザードンex", lang="JA"),
        card("sv3pt5", "151", "900", "Metapod", variants=(("Normal", 1),)),          # numero diverso: per nome
        card("zzz", "Set che non esiste", "1", "Mistero"),
        card("sv3pt5", "151", "998", "Carta inesistente"),
    ],
}


# --- lettura e abbinamento -------------------------------------------------------------------------------------

def test_set_codes_are_normalized():
    assert "sv03.5" in set_id_candidates("sv3pt5", "en")
    assert "me02.5" in set_id_candidates("me2pt5", "en")
    assert "sv01" in set_id_candidates("sv1", "en")
    assert set_id_candidates("me55", "en")[0] == "30th"
    assert "M5" in set_id_candidates("m5_ja", "ja")


def test_parse_export_reads_variants_and_languages():
    name, rows = parse_export(EXPORT)
    assert name == "le mie carte" and len(rows) == 5
    assert rows[0].quantity == 2 and rows[0].variant_name == "Holo" and rows[1].lang == "ja"
    with pytest.raises(ImportFormatError):
        parse_export({"foo": 1})


async def test_plan_matches_by_number_then_by_name(catalog):
    name, rows = parse_export(EXPORT)
    plan = await CollectionImporter(catalog).plan(name, rows)
    matched = {(m.catalog_lang, m.card_id): m for m in plan.matched}
    assert matched[("en", "sv03.5-006")].needs_review is False
    assert matched[("ja", "SV2a-185")].variant == "holo"
    metapod = [m for m in plan.matched if m.row.name == "Metapod"][0]
    assert metapod.needs_review is True and metapod.variant == "normal"
    reasons = sorted(r for _, r in plan.unmatched)
    assert len(reasons) == 2 and all("non trovat" in r for r in reasons)


async def test_apply_and_reimport_do_not_duplicate(catalog):
    sessions = make_session_factory(make_engine("sqlite://"))
    name, rows = parse_export(EXPORT)
    plan = await CollectionImporter(catalog).plan(name, rows)
    with sessions() as s:
        user, _ = get_or_create_user(s, "393330000000")
        first = apply_plan(s, user, plan)
        again = apply_plan(s, user, plan)
        assert first.cards == again.cards == 4 and s.query(CollectionItem).count() == 3
        assert s.query(Collection).count() == 1


async def test_refresh_fills_prices_images_and_value(catalog):
    sessions = make_session_factory(make_engine("sqlite://"))
    name, rows = parse_export(EXPORT)
    plan = await CollectionImporter(catalog).plan(name, rows)
    with sessions() as s:
        user, _ = get_or_create_user(s, "393330000000")
        report = apply_plan(s, user, plan)
    await refresh_items(sessions, catalog, report.item_ids)
    with sessions() as s:
        charizard = s.query(CollectionItem).filter_by(card_id="sv03.5-006").one()
        assert charizard.unit_price == 8.13 and charizard.id_product == 733601
        assert charizard.image.endswith("/low.webp") and charizard.number_label == "006/165"
        value = s.query(CollectionValue).one()
        assert value.cards == 4 and value.value >= round(8.13 * 2, 2)


async def test_nightly_update_prices_history_and_value(catalog):
    sessions = make_session_factory(make_engine("sqlite://"))
    name, rows = parse_export(EXPORT)
    plan = await CollectionImporter(catalog).plan(name, rows)
    with sessions() as s:
        user, _ = get_or_create_user(s, "393330000000")
        report = apply_plan(s, user, plan)
    await refresh_items(sessions, catalog, report.item_ids)
    entries = {733601: {"idProduct": 733601, "trend": 10.0, "avg7": 9.0, "avg30": 8.0, "low": 6.0, "trend-holo": 0}}
    with sessions() as s:
        stats = update_from_price_guide(s, entries, date(2026, 11, 19), extra_products={733601})
        s.commit()
        assert stats["items_priced"] == 1 and stats["history_rows"] == 1
        assert s.query(CollectionItem).filter_by(card_id="sv03.5-006").one().unit_price == 10.0
        h = s.query(PriceHistory).one()
        assert (h.id_product, h.fields, h.trend, h.low) == (733601, "base", 10.0, 6.0)
        assert s.query(CollectionValue).filter_by(day=date(2026, 11, 19)).one().value >= 20.0
        # Stesso giorno rielaborato: nessun doppione.
        update_from_price_guide(s, entries, date(2026, 11, 19))
        s.commit()
        assert s.query(PriceHistory).count() == 1


# --- API ----------------------------------------------------------------------------------------------------

def test_import_api_and_collection_detail(make_client):
    client, _ = logged(make_client)
    r = client.post("/api/collections/import", content=json.dumps(EXPORT),
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    rep = r.json()
    assert rep["imported"] == 3 and rep["cards"] == 4 and len(rep["unmatched"]) == 2 and len(rep["review"]) == 1
    cols = client.get("/api/collections").json()["collections"]
    assert cols[0]["name"] == "le mie carte" and cols[0]["cards"] == 4
    detail = client.get(f"/api/collections/{rep['collection_id']}").json()
    assert detail["items"][0]["card_id"] in ("SV2a-185", "sv03.5-006")  # ordinate per valore
    assert detail["value"] > 0 and detail["history"]


def test_import_rejects_bad_files(make_client):
    client, _ = logged(make_client)
    assert client.post("/api/collections/import", content=b"non json").status_code == 422
    assert client.post("/api/collections/import", content=b'{"cards": []}').status_code == 422


def test_add_from_card_page_and_owned_in_detail(make_client):
    client, _ = logged(make_client)
    body = {"card_id": "sv03.5-006", "catalog_lang": "en", "variant": "holo", "lang": "it", "quantity": 2}
    r = client.put("/api/collection-items", json=body).json()
    assert r["item"]["quantity"] == 2 and r["item"]["unit_price"] == 8.13 and r["item"]["total"] == 16.26
    owned = client.get("/api/cards/en/sv03.5-006").json()["owned"]
    assert owned[0]["lang"] == "it" and owned[0]["collection_name"] == "La mia collezione"
    # Quantità 0 = tolta dalla collezione.
    r = client.put("/api/collection-items", json={**body, "quantity": 0}).json()
    assert r["owned"] == []


def test_collections_are_private_to_their_owner(make_client):
    client, sessions = logged(make_client)
    with sessions() as s:
        other, _ = get_or_create_user(s, "390000000001")
        col = Collection(user_id=other.id, name="altrui")
        s.add(col)
        s.commit()
        cid = col.id
    assert client.get(f"/api/collections/{cid}").status_code == 404
    assert client.delete(f"/api/collections/{cid}").status_code == 404
