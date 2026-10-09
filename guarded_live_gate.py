"""Fail-closed policy gate for guarded autonomous Angel One orders."""
from __future__ import annotations

import math
import os
from pathlib import Path


class LiveOrderBlocked(RuntimeError):
    pass


def _truthy(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def _finite(value, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise LiveOrderBlocked(f"{label} is invalid") from exc
    if not math.isfinite(number):
        raise LiveOrderBlocked(f"{label} must be finite")
    return number


class GuardedLiveOrderGate:
    def __init__(self, kill_switch_path: str | None = None):
        self.kill_switch_path = Path(
            kill_switch_path or os.getenv("LIVE_KILL_SWITCH_FILE", "data/LIVE_KILL_SWITCH")
        )
        try:
            self.max_position_fraction = _finite(os.getenv("LIVE_MAX_POSITION_FRACTION", "0.06"), "position limit")
            self.max_total_exposure_fraction = _finite(os.getenv("LIVE_MAX_TOTAL_EXPOSURE_FRACTION", "0.30"), "exposure limit")
            self.max_daily_loss_fraction = _finite(os.getenv("LIVE_MAX_DAILY_LOSS_FRACTION", "0.03"), "daily loss limit")
            self.max_drawdown_fraction = _finite(os.getenv("LIVE_MAX_DRAWDOWN_FRACTION", "0.10"), "drawdown limit")
            self.max_quote_age_seconds = _finite(os.getenv("LIVE_MAX_QUOTE_AGE_SECONDS", "10"), "quote-age limit")
            self.max_orders_per_day = int(os.getenv("LIVE_MAX_ORDERS_PER_DAY", "10"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("live risk limits contain invalid values") from exc
        limits = (self.max_position_fraction, self.max_total_exposure_fraction,
                  self.max_daily_loss_fraction, self.max_drawdown_fraction,
                  self.max_quote_age_seconds)
        if not all(math.isfinite(value) and value > 0 for value in limits) or self.max_orders_per_day <= 0:
            raise ValueError("live risk limits must be finite and positive")
        self._approved_intents: set[str] = set()

    def check(self, request, intent_id: str, evidence: dict | None) -> dict:
        """Return approved decision or raise LiveOrderBlocked. Fail closed on missing data."""
        if not _truthy("LIVE_TRADING"):
            raise LiveOrderBlocked("live trading is disabled")
        if not _truthy("LIVE_AUTONOMOUS_GUARDED_APPROVED"):
            raise LiveOrderBlocked("guarded autonomous mode has not been explicitly armed")
        if not _truthy("CLOUD_RUNTIME") or not _truthy("LIVE_RUNTIME_APPROVED"):
            raise LiveOrderBlocked("approved cloud runtime is required")
        if os.getenv("LIVE_TRADING_ARM") != "I_UNDERSTAND_LIVE_TRADING":
            raise LiveOrderBlocked("live trading arm phrase is missing")
        if self.kill_switch_path.exists() or _truthy("LIVE_KILL_SWITCH"):
            raise LiveOrderBlocked("emergency kill switch is active")
        if not isinstance(evidence, dict):
            raise LiveOrderBlocked("broker-derived order evidence is required")

        required = (
            "authorized_quote", "quote_age_seconds", "contract_lot_size",
            "actual_contract_quantity", "margin_verified", "required_margin",
            "available_margin", "equity", "current_exposure",
            "daily_pnl", "peak_equity", "current_equity",
            "orders_today", "market_open", "risk_checks_passed",
            "protective_exit_verified", "broker_reconciliation_healthy",
        )
        missing = [key for key in required if key not in evidence]
        if missing:
            raise LiveOrderBlocked("missing safety evidence: " + ", ".join(missing))
        if evidence["authorized_quote"] is not True:
            raise LiveOrderBlocked("quote is not from the authorized broker feed")

        age = _finite(evidence["quote_age_seconds"], "quote age")
        lot_value = _finite(evidence["contract_lot_size"], "contract lot size")
        qty_value = _finite(getattr(request, "quantity", 0), "order quantity")
        required_margin = _finite(evidence["required_margin"], "required margin")
        available_margin = _finite(evidence["available_margin"], "available margin")
        equity = _finite(evidence["equity"], "equity")
        price = _finite(getattr(request, "price", 0), "order price")
        exposure = _finite(evidence["current_exposure"], "current exposure")
        daily_pnl = _finite(evidence["daily_pnl"], "daily P&L")
        peak_equity = _finite(evidence["peak_equity"], "peak equity")
        current_equity = _finite(evidence["current_equity"], "current equity")
        orders_value = _finite(evidence["orders_today"], "orders today")
        if not lot_value.is_integer() or not qty_value.is_integer() or not orders_value.is_integer():
            raise LiveOrderBlocked("lot size, quantity, and order count must be integers")
        lot, qty, orders_today = int(lot_value), int(qty_value), int(orders_value)

        if age < 0 or age > self.max_quote_age_seconds:
            raise LiveOrderBlocked("quote is stale or timestamp is invalid")
        if lot <= 0 or qty <= 0 or qty % lot != 0:
            raise LiveOrderBlocked("quantity must be a positive multiple of the actual contract lot size")
        if evidence["actual_contract_quantity"] is not True:
            raise LiveOrderBlocked("actual contract quantity is not verified")
        if evidence["margin_verified"] is not True:
            raise LiveOrderBlocked("broker margin is not verified")
        if required_margin <= 0 or available_margin < required_margin:
            raise LiveOrderBlocked("insufficient verified available margin")
        if equity <= 0:
            raise LiveOrderBlocked("equity must be positive")
        notional = price * qty
        if not math.isfinite(notional) or notional <= 0 or notional > equity * self.max_position_fraction:
            raise LiveOrderBlocked("order notional exceeds per-position cap")
        if exposure < 0 or exposure + notional / equity > self.max_total_exposure_fraction:
            raise LiveOrderBlocked("total exposure cap would be exceeded")
        if daily_pnl <= -(equity * self.max_daily_loss_fraction):
            raise LiveOrderBlocked("daily loss limit reached")
        if peak_equity <= 0 or current_equity <= 0:
            raise LiveOrderBlocked("equity history is invalid")
        drawdown = max(0.0, (peak_equity - current_equity) / peak_equity)
        if drawdown >= self.max_drawdown_fraction:
            raise LiveOrderBlocked("portfolio drawdown limit reached")
        if orders_today >= self.max_orders_per_day:
            raise LiveOrderBlocked("daily order-count limit reached")
        for key in ("market_open", "risk_checks_passed", "protective_exit_verified", "broker_reconciliation_healthy"):
            if evidence[key] is not True:
                raise LiveOrderBlocked(key + " gate is not satisfied")
        if not str(intent_id).strip():
            raise LiveOrderBlocked("stable intent ID is required")
        if str(intent_id) in self._approved_intents:
            raise LiveOrderBlocked("duplicate intent ID")
        return {
            "approved": True,
            "intent_id": str(intent_id),
            "notional": round(notional, 6),
            "drawdown_fraction": round(drawdown, 6),
            "mode": "guarded_autonomous",
        }

    def record_submitted(self, intent_id: str) -> None:
        self._approved_intents.add(str(intent_id))
