import pytest

from angelone_live_evidence import (
    AngelOneLiveEvidenceCollector,
    LiveOrderEvidenceUnavailable,
)


class Request:
    tradingsymbol = "GOLDM26OCTFUT"
    quantity = 1
    price = 5
    symboltoken = "123"
    exchange = "MCX"


def providers(**overrides):
    values = {
        "quote_provider": lambda request: {
            "last_price": 5.0, "timestamp": 1000.0, "authorized": True, "symboltoken": "123", "exchange": "MCX",
        },
        "instrument_provider": lambda request: {
            "lot_size": 1, "actual_quantity_verified": True,
        },
        "margin_provider": lambda request, quote: {
            "verified": True, "required_margin": 100.0, "available_margin": 1000.0,
        },
        "risk_state_provider": lambda: {
            "equity": 1000.0, "current_exposure": 0.0, "daily_pnl": 0.0,
            "peak_equity": 1000.0, "current_equity": 1000.0,
            "orders_today": 0, "checks_passed": True,
        },
        "market_open_provider": lambda request: True,
        "protective_exit_provider": lambda request: True,
        "reconciliation_provider": lambda: True,
        "clock": lambda: 1001.0,
    }
    values.update(overrides)
    return values


def test_missing_providers_fail_closed():
    collector = AngelOneLiveEvidenceCollector()
    with pytest.raises(LiveOrderEvidenceUnavailable, match="not configured"):
        collector.collect(Request())


def test_collects_complete_evidence_without_enabling_orders():
    collector = AngelOneLiveEvidenceCollector(**providers())
    result = collector.collect(Request())
    assert result["authorized_quote"] is True
    assert result["quote_age_seconds"] == 1.0
    assert result["contract_lot_size"] == 1
    assert result["margin_verified"] is True
    assert result["protective_exit_verified"] is True
    assert result["broker_reconciliation_healthy"] is True
    assert result["evidence_source"] == "angelone_provider_composition"


@pytest.mark.parametrize(
    "quote,match",
    [
        ({"last_price": 5.0, "timestamp": 900.0, "authorized": True, "symboltoken": "123", "exchange": "MCX"}, "stale"),
        ({"last_price": 5.0, "timestamp": 1000.0, "authorized": False, "symboltoken": "123", "exchange": "MCX"}, "authorized"),
        ({"last_price": 5.0, "authorized": True, "symboltoken": "123", "exchange": "MCX"}, "missing fields"),
    ],
)
def test_bad_quote_fails_closed(quote, match):
    collector = AngelOneLiveEvidenceCollector(**providers(
        quote_provider=lambda request: quote,
    ))
    with pytest.raises(LiveOrderEvidenceUnavailable, match=match):
        collector.collect(Request())


def test_unverified_margin_fails_closed():
    collector = AngelOneLiveEvidenceCollector(**providers(
        margin_provider=lambda request, quote: {
            "verified": False, "required_margin": 100.0, "available_margin": 1000.0,
        },
    ))
    with pytest.raises(LiveOrderEvidenceUnavailable, match="not verified"):
        collector.collect(Request())


def test_provider_exception_fails_closed():
    def broken():
        raise RuntimeError("broker unavailable")

    collector = AngelOneLiveEvidenceCollector(**providers(
        risk_state_provider=broken,
    ))
    with pytest.raises(LiveOrderEvidenceUnavailable, match="provider failed"):
        collector.collect(Request())


def test_unhealthy_reconciliation_fails_closed():
    collector = AngelOneLiveEvidenceCollector(**providers(
        reconciliation_provider=lambda: False,
    ))
    with pytest.raises(LiveOrderEvidenceUnavailable, match="reconciliation is unhealthy"):
        collector.collect(Request())


def test_closed_market_fails_closed():
    collector = AngelOneLiveEvidenceCollector(**providers(
        market_open_provider=lambda request: False,
    ))
    with pytest.raises(LiveOrderEvidenceUnavailable, match="market session is closed"):
        collector.collect(Request())


def test_unverified_protective_exit_fails_closed():
    collector = AngelOneLiveEvidenceCollector(**providers(
        protective_exit_provider=lambda request: False,
    ))
    with pytest.raises(LiveOrderEvidenceUnavailable, match="protective-exit handling"):
        collector.collect(Request())


def test_future_quote_timestamp_fails_closed():
    collector = AngelOneLiveEvidenceCollector(**providers(
        quote_provider=lambda request: {
            "last_price": 5.0, "timestamp": 1002.0, "authorized": True, "symboltoken": "123", "exchange": "MCX",
        },
    ))
    with pytest.raises(LiveOrderEvidenceUnavailable, match="future"):
        collector.collect(Request())


def test_quote_identity_must_match_request():
    collector = AngelOneLiveEvidenceCollector(**providers(
        quote_provider=lambda request: {
            "last_price": 5.0, "timestamp": 1000.0, "authorized": True,
            "symboltoken": "999", "exchange": "MCX",
        },
    ))
    with pytest.raises(LiveOrderEvidenceUnavailable, match="token does not match"):
        collector.collect(Request())


@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf")])
def test_non_positive_or_non_finite_quote_price_fails_closed(price):
    collector = AngelOneLiveEvidenceCollector(**providers(
        quote_provider=lambda request: {
            "last_price": price, "timestamp": 1000.0, "authorized": True,
            "symboltoken": "123", "exchange": "MCX",
        },
    ))
    with pytest.raises(LiveOrderEvidenceUnavailable):
        collector.collect(Request())
