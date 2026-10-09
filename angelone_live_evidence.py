"""Fail-closed composition layer for guarded Angel One order evidence.

This module deliberately does not guess account equity, margin, market hours,
protective exits, P&L, or reconciliation health. Those require independently
verified providers. Until every provider is configured and returns validated
data, collect() raises LiveOrderEvidenceUnavailable and no order can be approved.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any


class LiveOrderEvidenceUnavailable(RuntimeError):
    """Raised when any required live-order evidence source is absent or invalid."""


class AngelOneLiveEvidenceCollector:
    """Compose broker observations and separately verified risk-control results.

    Provider contracts:
      quote_provider(request) -> mapping containing last_price, timestamp,
        authorized (must be True), symboltoken and exchange
      instrument_provider(request) -> mapping containing lot_size and
        actual_quantity_verified (must be True)
      margin_provider(request, quote) -> mapping containing verified,
        required_margin, available_margin
      risk_state_provider() -> mapping containing equity, current_exposure,
        daily_pnl, peak_equity, current_equity, orders_today, checks_passed
      market_open_provider(request) -> bool
      protective_exit_provider(request) -> bool
      reconciliation_provider() -> bool

    Providers must be backed by live broker responses / durable local risk state.
    This class validates shape and freshness, but cannot prove a provider is
    honest or that the broker API semantics are correct. Keep LIVE_TRADING off
    until each provider is implemented and separately validated.
    """

    def __init__(
        self,
        *,
        quote_provider: Callable[[Any], dict] | None = None,
        instrument_provider: Callable[[Any], dict] | None = None,
        margin_provider: Callable[[Any, dict], dict] | None = None,
        risk_state_provider: Callable[[], dict] | None = None,
        market_open_provider: Callable[[Any], bool] | None = None,
        protective_exit_provider: Callable[[Any], bool] | None = None,
        reconciliation_provider: Callable[[], bool] | None = None,
        max_quote_age_seconds: float = 10.0,
        clock: Callable[[], float] = time.time,
    ):
        self.quote_provider = quote_provider
        self.instrument_provider = instrument_provider
        self.margin_provider = margin_provider
        self.risk_state_provider = risk_state_provider
        self.market_open_provider = market_open_provider
        self.protective_exit_provider = protective_exit_provider
        self.reconciliation_provider = reconciliation_provider
        self.max_quote_age_seconds = float(max_quote_age_seconds)
        if not math.isfinite(self.max_quote_age_seconds) or self.max_quote_age_seconds <= 0:
            raise ValueError("max_quote_age_seconds must be finite and positive")
        self.clock = clock

    def collect(self, request) -> dict:
        providers = {
            "authorized broker quote": self.quote_provider,
            "instrument master / lot size": self.instrument_provider,
            "broker margin calculation": self.margin_provider,
            "durable risk state": self.risk_state_provider,
            "market session guard": self.market_open_provider,
            "protective-exit verification": self.protective_exit_provider,
            "broker reconciliation": self.reconciliation_provider,
        }
        missing = [name for name, provider in providers.items() if not callable(provider)]
        if missing:
            raise LiveOrderEvidenceUnavailable(
                "live evidence providers not configured: " + ", ".join(missing)
            )

        try:
            quote = self.quote_provider(request)
            instrument = self.instrument_provider(request)
            margin = self.margin_provider(request, quote)
            risk = self.risk_state_provider()
            market_open = self.market_open_provider(request)
            protective_exit = self.protective_exit_provider(request)
            reconciled = self.reconciliation_provider()
        except Exception as exc:
            raise LiveOrderEvidenceUnavailable(
                "a required evidence provider failed; order must remain blocked"
            ) from exc

        if not all(isinstance(item, dict) for item in (quote, instrument, margin, risk)):
            raise LiveOrderEvidenceUnavailable("evidence providers returned invalid data")
        required_quote = ("last_price", "timestamp", "authorized", "symboltoken", "exchange")
        required_instrument = ("lot_size", "actual_quantity_verified")
        required_margin = ("verified", "required_margin", "available_margin")
        required_risk = (
            "equity", "current_exposure", "daily_pnl", "peak_equity",
            "current_equity", "orders_today", "checks_passed",
        )
        for label, data, fields in (
            ("quote", quote, required_quote),
            ("instrument", instrument, required_instrument),
            ("margin", margin, required_margin),
            ("risk state", risk, required_risk),
        ):
            absent = [field for field in fields if field not in data]
            if absent:
                raise LiveOrderEvidenceUnavailable(
                    f"{label} evidence missing fields: " + ", ".join(absent)
                )

        try:
            now = float(self.clock())
            quote_timestamp = float(quote["timestamp"])
            quote_price = float(quote["last_price"])
            age = now - quote_timestamp
            lot_value = float(instrument["lot_size"])
            lot = int(lot_value)
            if not lot_value.is_integer():
                raise ValueError("lot size must be an integer")
            required_margin_value = float(margin["required_margin"])
            available_margin = float(margin["available_margin"])
            equity = float(risk["equity"])
            current_exposure = float(risk["current_exposure"])
            daily_pnl = float(risk["daily_pnl"])
            peak_equity = float(risk["peak_equity"])
            current_equity = float(risk["current_equity"])
            orders_today_value = float(risk["orders_today"])
            orders_today = int(orders_today_value)
            numeric_values = (now, quote_timestamp, quote_price, required_margin_value,
                              available_margin, equity, current_exposure, daily_pnl,
                              peak_equity, current_equity, orders_today_value)
            if not all(math.isfinite(value) for value in numeric_values):
                raise ValueError("evidence contains non-finite numeric values")
            if not orders_today_value.is_integer():
                raise ValueError("order count must be an integer")
        except (TypeError, ValueError, OverflowError) as exc:
            raise LiveOrderEvidenceUnavailable("evidence contains invalid numeric values") from exc

        if quote["authorized"] is not True:
            raise LiveOrderEvidenceUnavailable("quote is not verified as authorized broker data")
        request_token = str(getattr(request, "symboltoken", "") or "").strip()
        request_exchange = str(getattr(request, "exchange", "") or "").strip().upper()
        if not request_token or str(quote["symboltoken"]).strip() != request_token:
            raise LiveOrderEvidenceUnavailable("quote token does not match the requested instrument")
        if not request_exchange or str(quote["exchange"]).strip().upper() != request_exchange:
            raise LiveOrderEvidenceUnavailable("quote exchange does not match the requested instrument")
        if quote_price <= 0:
            raise LiveOrderEvidenceUnavailable("broker quote price must be positive")
        if age < 0 or age > self.max_quote_age_seconds:
            raise LiveOrderEvidenceUnavailable("quote timestamp is stale or in the future")
        if lot <= 0 or instrument["actual_quantity_verified"] is not True:
            raise LiveOrderEvidenceUnavailable("actual instrument lot size/quantity is not verified")
        if margin["verified"] is not True or required_margin_value <= 0:
            raise LiveOrderEvidenceUnavailable("broker margin is not verified")
        if available_margin < required_margin_value:
            raise LiveOrderEvidenceUnavailable("verified available margin is insufficient")
        if equity <= 0 or current_equity <= 0 or peak_equity <= 0:
            raise LiveOrderEvidenceUnavailable("risk-state equity values must be positive")
        if current_exposure < 0 or orders_today < 0:
            raise LiveOrderEvidenceUnavailable("risk-state exposure/order count is invalid")
        if type(market_open) is not bool or type(protective_exit) is not bool or type(reconciled) is not bool:
            raise LiveOrderEvidenceUnavailable("market/protective-exit/reconciliation providers must return booleans")
        if risk["checks_passed"] is not True:
            raise LiveOrderEvidenceUnavailable("independent risk checks have not passed")

        return {
            "authorized_quote": True,
            "quote_age_seconds": age,
            "contract_lot_size": lot,
            "actual_contract_quantity": True,
            "margin_verified": True,
            "required_margin": required_margin_value,
            "available_margin": available_margin,
            "equity": equity,
            "current_exposure": current_exposure,
            "daily_pnl": daily_pnl,
            "peak_equity": peak_equity,
            "current_equity": current_equity,
            "orders_today": orders_today,
            "market_open": market_open,
            "risk_checks_passed": True,
            "protective_exit_verified": protective_exit,
            "broker_reconciliation_healthy": reconciled,
            "evidence_timestamp": self.clock(),
            "evidence_source": "angelone_provider_composition",
        }
