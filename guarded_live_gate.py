"""Fail-closed policy gate for guarded autonomous Angel One orders.

No broker calls happen here. A decision is allowed only when the caller supplies
fresh, broker-derived evidence for sizing, margin and exposure. The emergency
stop is a local file (default data/LIVE_KILL_SWITCH) or an explicit env flag.
"""
from __future__ import annotations

import os
from pathlib import Path


class LiveOrderBlocked(RuntimeError):
    pass


def _truthy(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


class GuardedLiveOrderGate:
    def __init__(self, kill_switch_path: str | None = None):
        self.kill_switch_path = Path(
            kill_switch_path or os.getenv("LIVE_KILL_SWITCH_FILE", "data/LIVE_KILL_SWITCH")
        )
        self.max_position_fraction = float(os.getenv("LIVE_MAX_POSITION_FRACTION", "0.06"))
        self.max_total_exposure_fraction = float(os.getenv("LIVE_MAX_TOTAL_EXPOSURE_FRACTION", "0.30"))
        self.max_daily_loss_fraction = float(os.getenv("LIVE_MAX_DAILY_LOSS_FRACTION", "0.03"))
        self.max_drawdown_fraction = float(os.getenv("LIVE_MAX_DRAWDOWN_FRACTION", "0.10"))
        self.max_quote_age_seconds = float(os.getenv("LIVE_MAX_QUOTE_AGE_SECONDS", "10"))
        self.max_orders_per_day = int(os.getenv("LIVE_MAX_ORDERS_PER_DAY", "10"))
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
        age = float(evidence["quote_age_seconds"])
        if age < 0 or age > self.max_quote_age_seconds:
            raise LiveOrderBlocked("quote is stale or timestamp is invalid")
        lot = int(evidence["contract_lot_size"])
        qty = int(getattr(request, "quantity", 0))
        if lot <= 0 or qty <= 0 or qty % lot != 0:
            raise LiveOrderBlocked("quantity must be a positive multiple of the actual contract lot size")
        if evidence["actual_contract_quantity"] is not True:
            raise LiveOrderBlocked("actual contract quantity is not verified")
        if evidence["margin_verified"] is not True:
            raise LiveOrderBlocked("broker margin is not verified")
        required_margin = float(evidence["required_margin"])
        available_margin = float(evidence["available_margin"])
        if required_margin <= 0 or available_margin < required_margin:
            raise LiveOrderBlocked("insufficient verified available margin")
        equity = float(evidence["equity"])
        if equity <= 0:
            raise LiveOrderBlocked("equity must be positive")
        notional = float(getattr(request, "price", 0)) * qty
        if notional <= 0 or notional > equity * self.max_position_fraction:
            raise LiveOrderBlocked("order notional exceeds per-position cap")
        exposure = float(evidence["current_exposure"])
        if exposure < 0 or exposure + notional / equity > self.max_total_exposure_fraction:
            raise LiveOrderBlocked("total exposure cap would be exceeded")
        daily_pnl = float(evidence["daily_pnl"])
        if daily_pnl <= -(equity * self.max_daily_loss_fraction):
            raise LiveOrderBlocked("daily loss limit reached")
        peak_equity = float(evidence["peak_equity"])
        current_equity = float(evidence["current_equity"])
        if peak_equity <= 0 or current_equity <= 0:
            raise LiveOrderBlocked("equity history is invalid")
        drawdown = max(0.0, (peak_equity - current_equity) / peak_equity)
        if drawdown >= self.max_drawdown_fraction:
            raise LiveOrderBlocked("portfolio drawdown limit reached")
        if int(evidence["orders_today"]) >= self.max_orders_per_day:
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
