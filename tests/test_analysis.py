"""Analisi "tengo o vendo": segnali, probabilità, dati di mercato del job e API."""

from datetime import date, timedelta

from cardbot.analysis.engine import MarketInputs, analyze
from cardbot.analysis.market import compute_set_stats, update_products
from cardbot.db import ProductInfo, SetStats, make_engine, make_session_factory
from tests.test_app_api import logged, make_client  # noqa: F401 (fixture)

TODAY = date(2026, 11, 19)


def test_rising_card_in_an_old_set_is_a_hold():
    a = analyze(MarketInputs(price=120, low=100, avg1=118, avg7=110, avg30=95, set_change_30d=0.05,
                             set_share_up=0.6, release_date=date(2023, 9, 22), rarity="Special illustration rare",
                             today=TODAY))
    assert a.verdict == "hold" and a.p_down < 0.42 and a.expected_change > 0
    assert a.range_low < 120 < a.range_high
    assert {s.key for s in a.signals} >= {"trend30", "trend7", "supply", "set", "age"}


def test_falling_card_in_a_new_set_with_a_reprint_leans_sell():
    a = analyze(MarketInputs(price=40, low=15, avg1=41, avg7=45, avg30=55, set_change_30d=-0.12, set_share_up=0.1,
                             release_date=TODAY - timedelta(days=20), reprinted_recently=True,
                             reprint_date=TODAY - timedelta(days=10), today=TODAY))
    assert a.verdict in ("sell", "consider_selling") and a.p_down > 0.58 and a.expected_change < 0
    reprint = [s for s in a.signals if s.key == "reprint"][0]
    assert reprint.direction == "down" and "09/11/2026" in reprint.detail


def test_cheap_cards_are_not_worth_selling_alone():
    a = analyze(MarketInputs(price=0.4, avg7=0.35, avg30=0.3, today=TODAY))
    assert a.verdict == "low_value" and "lotto" in a.summary


def test_little_data_means_low_confidence_and_cautious_probability():
    a = analyze(MarketInputs(price=10, avg7=13, today=TODAY))
    assert a.confidence == "bassa" and 0.3 < a.p_down < 0.7
    assert any("scarsi" in n for n in a.notes)


def test_our_history_adds_a_trend_signal_and_confidence():
    history = [(TODAY - timedelta(days=40 - i), 20 + i * 0.5) for i in range(40)]
    a = analyze(MarketInputs(price=40, avg7=38, avg30=33, history=history, set_change_30d=0.02, today=TODAY))
    sig = [s for s in a.signals if s.key == "history"][0]
    assert sig.direction == "up" and a.confidence == "alta"


def test_spike_detected_only_for_cards_worth_something():
    spike = analyze(MarketInputs(price=30, avg1=45, avg7=30, avg30=29, today=TODAY))
    assert any(s.key == "spike" for s in spike.signals)
    cheap = analyze(MarketInputs(price=2, avg1=3, avg7=2, avg30=2, today=TODAY))
    assert not any(s.key == "spike" for s in cheap.signals)


# --- dati del job ----------------------------------------------------------------------------------------------

def test_products_and_set_stats():
    sessions = make_session_factory(make_engine("sqlite://"))
    products = [{"idProduct": i, "idExpansion": 10, "idMetacard": 500 + i, "dateAdded": "2026-09-10 10:00:00",
                 "name": f"Carta {i}"} for i in range(1, 6)]
    products.append({"idProduct": 99, "idExpansion": 11, "idMetacard": 1, "dateAdded": "0000-00-00 00:00:00"})
    entries = {
        1: {"trend": 10, "avg7": 9, "avg30": 8},          # +25% a 30 gg
        2: {"trend": 5, "avg7": 5, "avg30": 6},           # −17%
        3: {"trend": 2, "avg7": 2, "avg30": 2},           # 0%
        4: {"trend": 0, "trend-holo": 3, "avg7-holo": 3, "avg30-holo": 2},  # solo holo: +50%
        5: {"trend": 0.2, "avg7": 0.2, "avg30": 0.1},    # sotto 0,50 €: escluso
    }
    with sessions() as s:
        assert update_products(s, products) == 6
        assert update_products(s, products) == 0          # già noti
        assert s.get(ProductInfo, 99).date_added is None
        assert compute_set_stats(s, entries, TODAY) == 1
        compute_set_stats(s, entries, TODAY)               # stesso giorno: aggiorna, non duplica
        s.commit()
        row = s.query(SetStats).one()
        assert row.cards == 4 and row.total_trend == 20
        assert abs(row.median_change_30d - 0.125) < 1e-3 and row.share_up_30d == 0.5


# --- API --------------------------------------------------------------------------------------------------------

def test_analysis_api(make_client):
    client, _ = logged(make_client)
    a = client.get("/api/cards/en/sv03.5-006/analysis", params={"variant": "holo"}).json()
    assert a["available"] is True and a["price"] == 8.13
    assert a["verdict"] in ("hold", "neutral", "consider_selling", "sell", "low_value")
    assert 0.1 <= a["p_down"] <= 0.9 and a["signals"] and a["averages"][-1]["label"] == "Oggi"
    assert "consiglio finanziario" in a["disclaimer"]
