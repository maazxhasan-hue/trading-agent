import pytest

from angelone_live_evidence import LiveOrderEvidenceUnavailable
from angelone_readonly_providers import AngelOneReadOnlyEvidenceProviders


class Request:
    tradingsymbol = "GOLDM26OCTFUT"
    symboltoken = "12345"
    exchange = "MCX"
    quantity = 1
    price = 5.0


class Broker:
    def __init__(self):
        self.quote_rows = {
            "12345": {
                "symbolToken": "12345", "ltp": 70000,
                "exchangeFeedTime": "09-Oct-2026 12:00:00",
            }
        }
        self.instrument_rows = [{
            "tradingsymbol": "GOLDM26OCTFUT", "symboltoken": "12345",
            "instrument_token": "12345", "exchange": "MCX", "lot_size": 1,
            "instrument_type": "FUTCOM", "expiry": "29OCT2026",
        }]

    def quote(self, tokens, exchange="NSE"):
        assert exchange == "MCX"
        return self.quote_rows

    def instruments(self, exchange="NSE"):
        return self.instrument_rows

    def funds_available(self, exchange="NSE"):
        return 50000.0

    def positions(self):
        return {"day": [], "net": []}

    def orders(self):
        return []


def test_quote_provider_validates_token_price_and_timestamp():
    providers = AngelOneReadOnlyEvidenceProviders(Broker(), clock=lambda: 1791547200)
    result = providers.quote_provider(Request())
    assert result["authorized"] is True
    assert result["symboltoken"] == "12345"
    assert result["last_price"] == 70000


def test_quote_missing_timestamp_fails_closed():
    broker = Broker()
    broker.quote_rows["12345"].pop("exchangeFeedTime")
    providers = AngelOneReadOnlyEvidenceProviders(broker)
    with pytest.raises(LiveOrderEvidenceUnavailable, match="timestamp"):
        providers.quote_provider(Request())


def test_instrument_provider_checks_exact_symbol_token_and_lot():
    providers = AngelOneReadOnlyEvidenceProviders(Broker())
    result = providers.instrument_provider(Request())
    assert result["lot_size"] == 1
    assert result["actual_quantity_verified"] is True


def test_instrument_quantity_not_multiple_of_lot_fails_closed():
    broker = Broker()
    broker.instrument_rows[0]["lot_size"] = 10
    providers = AngelOneReadOnlyEvidenceProviders(broker)
    with pytest.raises(LiveOrderEvidenceUnavailable, match="lot-size multiple"):
        providers.instrument_provider(Request())


def test_ambiguous_instrument_fails_closed():
    broker = Broker()
    broker.instrument_rows.append(dict(broker.instrument_rows[0]))
    providers = AngelOneReadOnlyEvidenceProviders(broker)
    with pytest.raises(LiveOrderEvidenceUnavailable, match="ambiguous"):
        providers.instrument_provider(Request())


def test_account_snapshot_labels_funds_as_funds_not_margin():
    providers = AngelOneReadOnlyEvidenceProviders(Broker(), clock=lambda: 42)
    snapshot = providers.account_snapshot()
    assert snapshot["available_funds"] == 50000
    assert "required_margin" not in snapshot
    assert snapshot["source"] == "angelone_smartapi_read_only_account"


def test_reconciliation_rejects_impossible_fill_quantity():
    broker = Broker()
    broker.orders = lambda: [{
        "order_id": "O1", "status": "COMPLETE",
        "quantity": 1, "filled_quantity": 2,
    }]
    providers = AngelOneReadOnlyEvidenceProviders(broker)
    assert providers.reconciliation_provider() is False
