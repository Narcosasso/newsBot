from cardbot.prices.models import cardmarket_quote, tcgplayer_quote
from cardbot.prices.service import PriceService
from tests.conftest import load


def _variant(card_file: str, idx: int):
    return load(card_file)["variants_detailed"][idx]


def test_reverse_on_shared_product_uses_holo_fields():
    pricing = _variant("en_cards_sv03.5-001.json", 1)["pricing"]["cardmarket"]
    q = cardmarket_quote(pricing, "reverse", shared_product=True)
    assert q.trend == pricing["trend-holo"] and q.avg30 == pricing["avg30-holo"]


def test_normal_uses_base_fields():
    pricing = _variant("en_cards_sv03.5-001.json", 0)["pricing"]["cardmarket"]
    q = cardmarket_quote(pricing, "normal", shared_product=True)
    assert q.trend == pricing["trend"] and q.low == pricing["low"]


def test_dedicated_product_with_empty_base_falls_back_to_holo_fields():
    # Reverse "cosmo" con prodotto dedicato: campi base vuoti, dati nei campi -holo.
    pricing = _variant("en_cards_sv03.5-001.json", 3)["pricing"]["cardmarket"]
    q = cardmarket_quote(pricing, "reverse", shared_product=False)
    assert q.trend == pricing["trend-holo"]


def test_zero_trend_means_no_data():
    q = cardmarket_quote({"idProduct": 1, "trend": 0, "low": None}, "normal", shared_product=False)
    assert q.trend is None and not q.has_data


def test_change_percentages():
    q = cardmarket_quote({"trend": 11.0, "avg7": 10.0, "avg30": 10.0}, "normal", shared_product=False)
    assert round(q.change_7d_pct, 1) == 10.0 and round(q.change_30d_pct, 1) == 10.0


def test_tcgplayer_variant_key():
    pricing = load("en_cards_sv03.5-006.json")["pricing"]["tcgplayer"]
    assert tcgplayer_quote(pricing, "holo").market == pricing["holofoil"]["marketPrice"]
    assert tcgplayer_quote(pricing, "reverse") is None


async def test_international_langs_are_grouped_and_aggregated(catalog):
    quotes = await PriceService(catalog).quotes("sv03.5-006", "en", "holo", ["it", "en"])
    assert len(quotes) == 1
    q = quotes[0]
    assert q.langs == ["it", "en"] and q.aggregated
    assert q.cardmarket.id_product == 733601 and q.cardmarket.trend == 8.13
    assert q.tcgplayer is not None  # ENG richiesto -> anche TCGplayer


async def test_tcgplayer_only_when_english_requested(catalog):
    quotes = await PriceService(catalog).quotes("sv03.5-006", "en", "holo", ["it"])
    assert quotes[0].tcgplayer is None


async def test_japanese_equivalent_has_own_product(catalog):
    quotes = await PriceService(catalog).quotes("sv03.5-006", "en", "holo", ["it", "ja"])
    jp = next(q for q in quotes if q.langs == ["ja"])
    assert jp.card_id == "SV2a-006" and jp.estimated_equivalent and not jp.aggregated
    assert jp.cardmarket.id_product == 719448


async def test_from_japanese_card_to_international(catalog):
    quotes = await PriceService(catalog).quotes("SV2a-006", "ja", "holo", ["ja", "en"])
    intl = next(q for q in quotes if "en" in q.langs)
    jp = next(q for q in quotes if q.langs == ["ja"])
    assert intl.card_id == "sv03.5-006" and intl.estimated_equivalent
    assert jp.card_id == "SV2a-006" and not jp.estimated_equivalent


async def test_korean_has_no_free_source(catalog):
    quotes = await PriceService(catalog).quotes("sv03.5-006", "en", "holo", ["ko"])
    assert quotes[0].cardmarket is None and "Nessuna fonte gratuita" in quotes[0].notes[0]


async def test_unknown_card(catalog):
    quotes = await PriceService(catalog).quotes("nope-1", "en", "holo", ["it"])
    assert quotes[0].card_id is None
