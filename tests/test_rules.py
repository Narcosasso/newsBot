from types import SimpleNamespace

import pytest

from cardbot.alerts.rules import Threshold, effective_threshold, evaluate, metric
from cardbot.prices.models import CardmarketQuote

DEFAULT = Threshold()  # 10% e 1 €


@pytest.mark.parametrize("baseline,current,notify", [
    (10.0, 11.0, True),    # +10% e +1 €: esattamente sulla soglia
    (10.0, 10.9, False),   # +9%
    (10.0, 8.9, True),     # -11% e -1,10 €: anche i ribassi
    (2.0, 2.5, False),     # +25% ma solo 0,50 €: carta economica, niente spam
    (100.0, 105.0, False), # +5 € ma solo +5%
    (100.0, 112.0, True),
    (10.0, 10.0, False),
])
def test_default_threshold_requires_both_conditions(baseline, current, notify):
    assert (evaluate(baseline, current, DEFAULT) is not None) is notify


def test_change_values():
    change = evaluate(10.0, 12.5, DEFAULT)
    assert change.delta == 2.5 and change.pct == 25.0


def test_missing_values_never_notify():
    assert evaluate(None, 10.0, DEFAULT) is None
    assert evaluate(10.0, None, DEFAULT) is None
    assert evaluate(0.0, 10.0, DEFAULT) is None


def test_only_percentage_threshold():
    th = Threshold(pct=15, eur=None)
    assert evaluate(2.0, 2.4, th) is not None       # +20%, anche se solo 0,40 €
    assert evaluate(2.0, 2.2, th) is None


def test_only_euro_threshold():
    th = Threshold(pct=None, eur=2)
    assert evaluate(100.0, 102.0, th) is not None   # +2% ma +2 €
    assert evaluate(100.0, 101.0, th) is None


def test_no_threshold_means_any_change():
    th = Threshold(pct=None, eur=None)
    assert evaluate(1.0, 1.01, th) is not None


def test_cumulative_drift_is_caught_against_baseline():
    """+4% al giorno non supera mai la soglia giorno su giorno, ma rispetto al riferimento sì."""
    baseline, price, notified = 10.0, 10.0, []
    for _ in range(5):
        price = round(price * 1.04, 2)
        if (change := evaluate(baseline, price, DEFAULT)) is not None:
            notified.append(change.new)
            baseline = change.new  # dopo la notifica il riferimento diventa il nuovo prezzo
    assert notified == [11.25]  # terzo giorno: +12,5% e +1,25 € rispetto al valore iniziale


def test_effective_threshold_custom_wins():
    user = SimpleNamespace(threshold_pct=10.0, threshold_eur=1.0)
    assert effective_threshold(user, SimpleNamespace(threshold_custom=False)) == Threshold(10.0, 1.0)
    custom = SimpleNamespace(threshold_custom=True, threshold_pct=20.0, threshold_eur=None)
    assert effective_threshold(user, custom) == Threshold(20.0, None)


def test_metric_prefers_trend_then_avg7():
    q = CardmarketQuote(id_product=1, low=1, trend=None, avg=3, avg1=None, avg7=2.0, avg30=None, updated=None)
    assert metric(q) == 2.0
    q.trend = 2.345
    assert metric(q) == 2.35
    assert metric(None) is None


def test_describe():
    assert Threshold().describe() == "10% e 1,00 €"
    assert Threshold(pct=None, eur=None).describe() == "qualsiasi variazione"
