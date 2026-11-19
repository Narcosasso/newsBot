"""Espansioni (serie e set con il completamento della collezione) e Pokédex (Pokémon posseduti)."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from functools import lru_cache
from importlib import resources
from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from cardbot import images
from cardbot.collections.service import refresh_items
from cardbot.db import Collection, CollectionItem, User
from cardbot.web.search import ZH, fill_missing_images, summary

CATALOGS = {"en": "en", "ja": "ja", "zh": ZH, ZH: ZH}
HIDDEN_SERIES = {"tcgp"}  # Pokémon TCG Pocket: solo digitale


@lru_cache(maxsize=1)
def pokedex() -> list[tuple[int, str, int]]:
    """(numero, nome, generazione) dei 1025 Pokémon (dati PokéAPI)."""
    raw = resources.files("cardbot").joinpath("data/pokedex.json").read_text(encoding="utf-8")
    return [tuple(x) for x in json.loads(raw)]


def owned_items(session: Session, user: User) -> list[CollectionItem]:
    """Carte possedute (escluse le liste desideri)."""
    return (session.query(CollectionItem).join(Collection)
            .filter(Collection.user_id == user.id, Collection.kind == "collection").all())


def owned_by_card(session: Session, user: User) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = defaultdict(int)
    for i in owned_items(session, user):
        out[(i.catalog_lang, i.card_id)] += i.quantity
    return out


def _logo(base: str | None) -> str | None:
    return f"{base}.webp" if base else None


def add_browse_routes(router: APIRouter, current_user: Callable, db: Callable, container: Callable) -> None:

    @router.get("/sets")
    async def list_sets(lang: str = "en", user: User = Depends(current_user), session: Session = Depends(db),
                        c=Depends(container)) -> dict[str, Any]:
        cl = CATALOGS.get(lang, "en")
        series = [s for s in await c.catalog.list_series(cl) if s.get("id") not in HIDDEN_SERIES]
        details = await asyncio.gather(*(c.catalog.get_series(cl, s["id"]) for s in series))
        owned: dict[str, set[str]] = defaultdict(set)
        for i in owned_items(session, user):
            if i.catalog_lang == cl and i.set_id:
                owned[i.set_id].add(i.card_id)
        out = []
        for s, d in zip(series, details):
            sets = [{"id": x["id"], "name": x.get("name", x["id"]),
                     "logo": _logo(x.get("logo")) or images.logo_url(x["id"], cl),
                     "symbol": _logo(x.get("symbol")), "total": (x.get("cardCount") or {}).get("total"),
                     "official": (x.get("cardCount") or {}).get("official"), "owned": len(owned.get(x["id"], ()))}
                    for x in reversed((d or {}).get("sets") or [])]
            if sets:
                out.append({"id": s["id"], "name": s.get("name", s["id"]), "logo": _logo(s.get("logo")),
                            "release_date": (d or {}).get("releaseDate"), "sets": sets})
        # Dalla serie più recente; "Varie" (promo e speciali) in fondo.
        out.sort(key=lambda s: (s["id"] == "misc", -(int((s["release_date"] or "0")[:4] or 0))))
        return {"series": out, "owned_sets": sum(1 for v in owned.values() if v)}

    @router.get("/sets/{lang}/{set_id}")
    async def get_set(lang: str, set_id: str, user: User = Depends(current_user), session: Session = Depends(db),
                      c=Depends(container)) -> dict[str, Any]:
        cl = CATALOGS.get(lang, lang)
        detail = await c.catalog.get_set(cl, set_id)
        if detail is None:
            raise HTTPException(404, "Espansione non trovata")
        mine = [i for i in owned_items(session, user) if i.catalog_lang == cl and i.set_id == set_id]
        qty: dict[str, int] = defaultdict(int)
        for i in mine:
            qty[i.card_id] += i.quantity
        cards = await fill_missing_images(c.catalog, [summary(x, cl, detail) for x in detail.get("cards") or []])
        for card in cards:
            card["owned"] = qty.get(card["id"], 0)
        count = detail.get("cardCount") or {}
        return {
            "id": detail["id"], "catalog_lang": cl, "name": detail.get("name"),
            "logo": _logo(detail.get("logo")) or images.logo_url(detail["id"], cl),
            "symbol": _logo(detail.get("symbol")), "serie": (detail.get("serie") or {}).get("name"),
            "code": (detail.get("abbreviation") or {}).get("official") or detail["id"],
            "release_date": detail.get("releaseDate"), "total": count.get("total") or len(cards),
            "official": count.get("official"), "owned_unique": len(qty), "owned_cards": sum(qty.values()),
            "owned_value": round(sum((i.unit_price or 0) * i.quantity for i in mine), 2), "cards": cards,
        }

    @router.get("/pokedex")
    def get_pokedex(tasks: BackgroundTasks, user: User = Depends(current_user), session: Session = Depends(db),
                    c=Depends(container)) -> dict[str, Any]:
        items = owned_items(session, user)
        counts: dict[int, int] = defaultdict(int)
        missing = [i.id for i in items if i.dex_ids is None]
        for i in items:
            for n in filter(None, (i.dex_ids or "").split(",")):
                counts[int(n)] += i.quantity
        if missing:  # carte importate prima che salvassimo il numero Pokédex: si completa in background
            tasks.add_task(refresh_items, c.sessions, c.catalog, missing)
        dex = pokedex()
        return {"pokemon": [[n, name, gen, counts.get(n, 0)] for n, name, gen in dex],
                "owned_species": sum(1 for n, _, _ in dex if counts.get(n)), "total": len(dex),
                "pending": len(missing)}
