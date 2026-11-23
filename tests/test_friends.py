"""Amici: inviti, accesso con PIN personale, collezioni visibili, incroci desideri/doppioni, scambi."""

from fastapi.testclient import TestClient

from cardbot.db import CollectionItem, User
from tests.test_app_api import PIN, logged, make_client  # noqa: F401 (fixture)

FRIEND_PIN = "246810"


def _friend(make_client):
    owner, sessions = logged(make_client)
    code = owner.post("/api/invites").json()["code"]
    friend = TestClient(owner.app)
    assert friend.get(f"/api/invites/{code}").json()["inviter"] == "Proprietario"
    r = friend.post(f"/api/invites/{code}/accept", json={"name": "Marco", "pin": FRIEND_PIN})
    assert r.status_code == 200 and "pv_session=" in r.headers["set-cookie"]
    return owner, friend, sessions


def _add(client, card="sv03.5-006", qty=1, wishlist=False, lang="it"):
    r = client.put("/api/collection-items", json={"card_id": card, "catalog_lang": "en", "variant": "holo",
                                                  "lang": "any" if wishlist else lang, "quantity": qty,
                                                  "wishlist": wishlist})
    assert r.status_code == 200, r.text
    return r.json()["item"]


def _ids(sessions):
    with sessions() as s:
        return {u.display_name or "owner": u.id for u in s.query(User).all()}


def test_invite_creates_account_friendship_and_pin_login(make_client):
    owner, friend, sessions = _friend(make_client)
    me = friend.get("/api/me").json()
    assert me["name"] == "Marco" and me["owner"] is False
    assert [f["name"] for f in owner.get("/api/friends").json()["friends"]] == ["Marco"]
    assert [f["name"] for f in friend.get("/api/friends").json()["friends"]] == ["Proprietario"]
    # L'invito è usa e getta; il PIN dell'amico apre il suo account.
    code = owner.post("/api/invites").json()["code"]
    other = TestClient(owner.app)
    assert other.post(f"/api/invites/{code}/accept", json={"name": "Luca", "pin": FRIEND_PIN}).status_code == 422
    assert other.post(f"/api/invites/{code}/accept", json={"name": "Luca", "pin": PIN}).status_code == 422
    assert other.post(f"/api/invites/{code}/accept", json={"name": "Luca", "pin": "12"}).status_code == 422
    fresh = TestClient(owner.app)
    assert fresh.post("/api/login", json={"pin": FRIEND_PIN}).status_code == 200
    assert fresh.get("/api/me").json()["name"] == "Marco"
    with sessions() as s:
        marco = s.query(User).filter_by(display_name="Marco").one()
        assert marco.wa_id.startswith("app:") and FRIEND_PIN not in (marco.pin_hash or "")


def test_friend_sees_visible_collections_without_values_unless_allowed(make_client):
    owner, friend, sessions = _friend(make_client)
    _add(owner, qty=2)
    f = friend.get("/api/friends").json()["friends"][0]
    col = [c for c in f["collections"] if c["kind"] == "collection"][0]
    assert col["cards"] == 2 and "value" not in col
    d = friend.get(f"/api/friends/{f['id']}/collections/{col['id']}").json()
    assert d["items"][0]["unit_price"] is None and d["items"][0]["card_id"] == "sv03.5-006"
    owner.patch(f"/api/collections/{col['id']}/privacy", json={"show_values": True})
    d = friend.get(f"/api/friends/{f['id']}/collections/{col['id']}").json()
    assert d["items"][0]["unit_price"] == 8.13 and d["value"] == 16.26
    owner.patch(f"/api/collections/{col['id']}/privacy", json={"visibility": "private"})
    assert friend.get(f"/api/friends/{f['id']}/collections/{col['id']}").status_code == 404
    # Gli estranei non vedono nulla.
    assert owner.get("/api/friends/999/collections/1").status_code == 404


def test_matches_and_full_trade_with_undo(make_client):
    owner, friend, sessions = _friend(make_client)
    give = _add(owner, "sv03.5-006", qty=2)            # doppione del proprietario
    want = _add(friend, "sv03.5-199", qty=1)            # carta di Marco che il proprietario cerca
    _add(owner, "sv03.5-199", wishlist=True)
    _add(friend, "sv03.5-006", wishlist=True)
    ids = _ids(sessions)
    marco_id = ids["Marco"]
    m = owner.get(f"/api/friends/{marco_id}/matches").json()
    assert [i["card_id"] for i in m["they_have"]] == ["sv03.5-199"]
    assert [i["card_id"] for i in m["you_have"]] == ["sv03.5-006"]

    r = owner.post("/api/trades", json={"friend_id": marco_id, "give": [{"item_id": give["id"], "quantity": 1}],
                                         "take": [{"item_id": want["id"], "quantity": 1}], "message": "Ci stai?"})
    assert r.status_code == 200, r.text
    t = r.json()["trade"]
    assert t["status"] == "proposed" and t["give_value"] == 8.13 and t["take"][0]["card_id"] == "sv03.5-199"
    inbox = friend.get("/api/trades").json()
    assert inbox["pending"] == 1 and inbox["trades"][0]["role"] == "recipient"
    # Solo chi riceve può accettare.
    assert owner.post(f"/api/trades/{t['id']}/accept").status_code == 422
    assert friend.post(f"/api/trades/{t['id']}/accept").json()["trade"]["status"] == "accepted"
    assert owner.post(f"/api/trades/{t['id']}/confirm").json()["trade"]["status"] == "accepted"
    done = friend.post(f"/api/trades/{t['id']}/confirm").json()["trade"]
    assert done["status"] == "completed" and done["can_undo"]

    def holdings(uid):
        with sessions() as s:
            return {(i.card_id, i.collection.kind): i.quantity for i in s.query(CollectionItem).all()
                    if i.collection.user_id == uid}
    owner_id = [v for k, v in ids.items() if k != "Marco"][0]
    assert holdings(owner_id) == {("sv03.5-006", "collection"): 1, ("sv03.5-199", "collection"): 1}
    assert holdings(marco_id) == {("sv03.5-006", "collection"): 1}   # ricevuta: tolta dai desideri

    assert friend.post(f"/api/trades/{t['id']}/undo").json()["trade"]["status"] == "undone"
    assert holdings(owner_id) == {("sv03.5-006", "collection"): 2, ("sv03.5-199", "wishlist"): 1}
    assert holdings(marco_id) == {("sv03.5-199", "collection"): 1, ("sv03.5-006", "wishlist"): 1}


def test_counter_reject_and_validation(make_client):
    owner, friend, sessions = _friend(make_client)
    mine = _add(owner, "sv03.5-006", qty=1)
    theirs = _add(friend, "sv03.5-199", qty=1)
    marco_id = _ids(sessions)["Marco"]
    owner_id = [v for k, v in _ids(sessions).items() if k != "Marco"][0]
    # Più copie di quelle che hai: rifiutato.
    bad = owner.post("/api/trades", json={"friend_id": marco_id, "give": [{"item_id": mine["id"], "quantity": 3}]})
    assert bad.status_code == 422
    t = owner.post("/api/trades", json={"friend_id": marco_id,
                                        "take": [{"item_id": theirs["id"], "quantity": 1}]}).json()["trade"]
    counter = friend.post("/api/trades", json={"friend_id": owner_id, "parent_id": t["id"],
                                               "give": [{"item_id": theirs["id"], "quantity": 1}],
                                               "take": [{"item_id": mine["id"], "quantity": 1}]}).json()["trade"]
    statuses = {x["id"]: x["status"] for x in owner.get("/api/trades").json()["trades"]}
    assert statuses[t["id"]] == "countered" and statuses[counter["id"]] == "proposed"
    assert owner.post(f"/api/trades/{counter['id']}/reject").json()["trade"]["status"] == "rejected"


def test_friends_cannot_use_shared_psa_alerts(make_client):
    _, friend, _ = _friend(make_client)
    r = friend.put("/api/tracking", json={"card_id": "sv03.5-006", "catalog_lang": "en", "variant": "holo",
                                          "langs": ["it"], "psa": True}).json()
    assert r["tracking"]["psa"] is False
