import pytest

from angelone_live_evidence import (
    AngelOneLiveEvidenceCollector,
    LiveOrderEvidenceUnavailable,
)


class Request:
    tradingsymbol = "GOLDM26OCTFUT"
    quantity = 1
    price = 5


def providers(**overrides):
    values = {
        "quote_provider": lambda request: {
            "last_price": 5.0, "timestamp": 1000.0, "authorized": True,
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
        ({"last_price": 5.0, "timestamp": 900.0, "authorized": True}, "stale"),
        ({"last_price": 5.0, "timestamp": 1000.0, "authorized": False}, "authorized"),
        ({"last_price": 5.0, "authorized": True}, "missing fields"),
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


def test_unhealthy_reconciliation_is_returned_as_false_for_gate_to_block():
    collector = AngelOneLiveEvidenceCollector(**providers(
        reconciliation_provider=lambda: False,
    ))
    result = collector.collect(Request())
    assert result["broker_reconciliation_healthy"] is False


def test_future_quote_timestamp_fails_closed():
    collector = AngelOneLiveEvidenceCollector(**providers(
        quote_provider=lambda request: {
            "last_price": 5.0, "timestamp": 1002.0, "authorized": True,
        },
    ))
    with pytest.raises(LiveOrderEvidenceUnavailable, match="future"):
        collector.collect(Request())
