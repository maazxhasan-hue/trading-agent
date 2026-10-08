import os

from angelone_adapter import AngelOneExecution, AngelOneLocked, OrderRequest


def test_angel_one_defaults_to_paper_mode(monkeypatch):
    monkeypatch.setenv("TRADING_BACKEND", "angelone_nse")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.delenv("ANGELONE_READONLY", raising=False)
    broker = AngelOneExecution()
    assert broker.enabled is False
    assert broker.client is None


def test_live_mode_fails_closed_without_runtime_credentials(monkeypatch):
    monkeypatch.setenv("TRADING_BACKEND", "angelone_nse")
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("LIVE_TRADING_ARM", "I_UNDERSTAND_LIVE_TRADING")
    monkeypatch.setenv("CLOUD_RUNTIME", "true")
    monkeypatch.setenv("LIVE_RUNTIME_APPROVED", "true")
    for key in (
        "ANGELONE_API_KEY",
        "ANGELONE_CLIENT_CODE",
        "ANGELONE_PIN",
        "ANGELONE_TOTP_SECRET",
        "ANGELONE_CLIENT_PUBLIC_IP",
    ):
        monkeypatch.delenv(key, raising=False)
    try:
        AngelOneExecution()
    except AngelOneLocked as exc:
        assert "Missing Angel One runtime settings" in str(exc)
    else:
        raise AssertionError("live Angel One mode must fail closed")


def test_order_request_is_explicit():
    request = OrderRequest(
        tradingsymbol="SBIN-EQ",
        symboltoken="3045",
        exchange="NSE",
        transaction_type="BUY",
        quantity=1,
        price=100.0,
    )
    assert request.symboltoken == "3045"
    assert request.product == "INTRADAY"


def test_order_normalization():
    row = {
        "orderid": "123",
        "status": "complete",
        "quantity": "5",
        "filledshares": "5",
        "averageprice": "100.25",
        "tradingsymbol": "SBIN-EQ",
        "transactiontype": "BUY",
        "ordertag": "nse-test",
    }
    normalized = AngelOneExecution._normalize_order(row)
    assert normalized["order_id"] == "123"
    assert normalized["filled_quantity"] == 5
    assert normalized["average_price"] == 100.25


def test_angel_one_mcx_defaults_to_paper_mode(monkeypatch):
    monkeypatch.setenv("TRADING_BACKEND", "angelone_mcx")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.delenv("ANGELONE_READONLY", raising=False)
    broker = AngelOneExecution()
    assert broker.enabled is False
    assert broker.client is None
    assert broker.status()["backend"] == "angelone_mcx"


def test_mcx_exchange_is_explicit_in_requests():
    import inspect
    assert "exchange" in inspect.signature(AngelOneExecution.quote).parameters
    assert "exchange" in inspect.signature(AngelOneExecution.historical).parameters


def test_mcx_live_order_rejects_non_mcx_exchange():
    broker = AngelOneExecution.__new__(AngelOneExecution)
    broker.enabled = True
    broker.armed = True
    broker.cloud_runtime = True
    broker.live_runtime_approved = True
    broker.backend = "angelone_mcx"
    broker.client = None
    request = OrderRequest(
        tradingsymbol="SBIN-EQ",
        symboltoken="3045",
        exchange="NSE",
        transaction_type="BUY",
        quantity=1,
        price=100.0,
        product="CARRYFORWARD",
    )
    try:
        broker.place_limit(request)
    except AngelOneLocked as exc:
        assert "refuses non-MCX" in str(exc)
    else:
        raise AssertionError("MCX backend must reject non-MCX orders")
