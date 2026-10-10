"""Concrete read-only Angel One evidence adapters.

This module only calls market-data/account-read methods on AngelOneExecution.
It never places, modifies, or cancels orders and does not enable live trading.
Unverified margin calculation, market-session, durable risk, and protective-exit
providers remain intentionally external and fail closed in the collector.
"""
from __future__ import annotations

import math
import time
from datetime import datetime

from angelone_live_evidence import LiveOrderEvidenceUnavailable


def _number(value, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise LiveOrderEvidenceUnavailable(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise LiveOrderEvidenceUnavailable(f"{label} is not finite")
    return result


def _timestamp(row: dict) -> float:
    raw = (
        row.get("exchangeFeedTime")
        or row.get("exchangeTradeTime")
        or row.get("exchTradeTime")
        or row.get("lastTradeTime")
        or row.get("timestamp")
    )
    if raw is None:
        raise LiveOrderEvidenceUnavailable("broker quote has no exchange timestamp")
    if isinstance(raw, (int, float)):
        value = float(raw)
        if not math.isfinite(value):
            raise LiveOrderEvidenceUnavailable("broker quote timestamp is invalid")
        return value / 1000.0 if value > 10_000_000_000 else value
    value = str(raw).strip()
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt).timestamp()
        except ValueError:
            continue
    raise LiveOrderEvidenceUnavailable("broker quote timestamp format is unsupported")


class AngelOneReadOnlyEvidenceProviders:
    """Adapt authenticated read-only SmartAPI methods to evidence provider callables.

    Construct with an existing AngelOneExecution configured for read-only access.
    The caller must still provide independently validated margin, market-session,
    durable-risk and protective-exit providers to AngelOneLiveEvidenceCollector.
    """

    def __init__(self, broker, *, clock=time.time):
        self.broker = broker
        self.clock = clock

    @staticmethod
    def _request_fields(request):
        symbol = str(getattr(request, "tradingsymbol", "") or "").strip()
        token = str(getattr(request, "symboltoken", "") or "").strip()
        exchange = str(getattr(request, "exchange", "") or "").strip().upper()
        if not symbol or not token or not exchange:
            raise LiveOrderEvidenceUnavailable("request must include symbol, symboltoken and exchange")
        if exchange not in {"MCX", "NSE", "NFO", "BSE", "BFO"}:
            raise LiveOrderEvidenceUnavailable("unsupported exchange for read-only evidence")
        return symbol, token, exchange

    def quote_provider(self, request) -> dict:
        symbol, token, exchange = self._request_fields(request)
        quotes = self.broker.quote([token], exchange=exchange)
        row = quotes.get(token) if isinstance(quotes, dict) else None
        if not isinstance(row, dict):
            raise LiveOrderEvidenceUnavailable("Angel One returned no quote for requested token")
        returned_token = str(row.get("symbolToken") or row.get("symboltoken") or token)
        if returned_token != token:
            raise LiveOrderEvidenceUnavailable("broker quote token does not match request")
        raw_price = (
            row.get("ltp") or row.get("lastTradedPrice") or row.get("last_price")
            or row.get("lastTradedPrice")
        )
        price = _number(raw_price, "broker last price")
        if price <= 0:
            raise LiveOrderEvidenceUnavailable("broker last price must be positive")
        return {
            "last_price": price,
            "timestamp": _timestamp(row),
            "authorized": True,
            "symboltoken": returned_token,
            "tradingsymbol": symbol,
            "exchange": exchange,
            "source": "angelone_smartapi_market_data",
        }

    def instrument_provider(self, request) -> dict:
        symbol, token, exchange = self._request_fields(request)
        rows = self.broker.instruments(exchange)
        matches = [
            row for row in rows
            if str(row.get("symboltoken") or row.get("instrument_token") or "") == token
            and str(row.get("tradingsymbol") or "").upper() == symbol.upper()
            and str(row.get("exchange") or "").upper() == exchange
        ]
        if len(matches) != 1:
            raise LiveOrderEvidenceUnavailable("instrument master match is missing or ambiguous")
        row = matches[0]
        try:
            lot_size = int(row["lot_size"])
            quantity = int(getattr(request, "quantity", 0))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise LiveOrderEvidenceUnavailable("instrument lot size or order quantity is invalid") from exc
        if lot_size <= 0 or quantity <= 0 or quantity % lot_size:
            raise LiveOrderEvidenceUnavailable("requested quantity is not a positive lot-size multiple")
        return {
            "lot_size": lot_size,
            "actual_quantity_verified": True,
            "symboltoken": token,
            "tradingsymbol": symbol,
            "exchange": exchange,
            "instrument_type": str(row.get("instrument_type") or ""),
            "expiry": row.get("expiry"),
        }

    def account_snapshot(self) -> dict:
        """Return broker-read funds, positions and order book for reconciliation.

        'available_funds' is a broker-reported account field, NOT an MCX contract
        margin calculation. Consumers must not map it to required_margin.
        """
        # RMS funds are account-level broker figures, not segment-specific margin.
        # Do not hardcode MCX here: this snapshot is shared by NSE and MCX logic.
        funds = self.broker.funds_available()
        positions_result = self.broker.positions()
        orders = self.broker.orders()
        if funds is None:
            raise LiveOrderEvidenceUnavailable("Angel One did not return available funds")
        funds = _number(funds, "broker available funds")
        if funds < 0:
            raise LiveOrderEvidenceUnavailable("broker available funds is negative")
        if not isinstance(positions_result, dict) or not isinstance(orders, list):
            raise LiveOrderEvidenceUnavailable("broker positions/orders response is malformed")
        day_positions = positions_result.get("day")
        net_positions = positions_result.get("net")
        if not isinstance(day_positions, list) or not isinstance(net_positions, list):
            raise LiveOrderEvidenceUnavailable("broker position snapshot is incomplete")
        return {
            "available_funds": funds,
            "day_positions": day_positions,
            "net_positions": net_positions,
            "orders": orders,
            "captured_at": self.clock(),
            "source": "angelone_smartapi_read_only_account",
        }

    def reconciliation_provider(self) -> bool:
        """Conservative consistency check; does not replace fill-level reconciliation."""
        snapshot = self.account_snapshot()
        for order in snapshot["orders"]:
            if not isinstance(order, dict):
                return False
            if not order.get("order_id") or not order.get("status"):
                return False
            quantity = order.get("quantity")
            filled = order.get("filled_quantity")
            try:
                quantity, filled = int(quantity), int(filled)
            except (TypeError, ValueError, OverflowError):
                return False
            if quantity < 0 or filled < 0 or filled > quantity:
                return False
        for position in snapshot["day_positions"] + snapshot["net_positions"]:
            if not isinstance(position, dict) or not position.get("tradingsymbol"):
                return False
            try:
                int(position["quantity"])
            except (KeyError, TypeError, ValueError, OverflowError):
                return False
        # Healthy here means structurally consistent only; the evidence label
        # makes clear this is not proof of fills matching every strategy intent.
        return True
