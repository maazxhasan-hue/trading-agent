"""Evidence collector for Angel One MCX paper validation.

This module is deliberately read-only: it consumes quote/portfolio/trade
observations and emits a report, but never submits broker orders or marks a
candidate live-ready. Promotion still requires TournamentLedger's separate gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable


class AngelOneMCXValidationReport:
    def __init__(self, max_quote_age_seconds=10.0, max_drawdown_fraction=0.10):
        self.max_quote_age_seconds = max(0.0, float(max_quote_age_seconds))
        self.max_drawdown_fraction = max(0.0, float(max_drawdown_fraction))
        self.started_at = datetime.now(timezone.utc)
        self.observations = []
        self.trades = []
        self.risk_violations = 0

    def observe_quotes(self, markets: Iterable, freshness_seconds, actual_contract_sizing=True):
        """Record feed label, quote age, price and lot size for one market snapshot."""
        for market in markets:
            try:
                age = float(freshness_seconds(market))
            except Exception:
                age = float("inf")
            price = float(getattr(market, "last_price", 0) or 0)
            lot = int(getattr(market, "lot_size", 0) or 0)
            valid = (
                price > 0 and lot > 0 and age >= 0
                and age <= self.max_quote_age_seconds
            )
            self.observations.append({
                "market_id": str(getattr(market, "market_id", "")),
                "tradingsymbol": str(getattr(market, "tradingsymbol", "")),
                "price": price,
                "lot_size": lot,
                "quote_age_seconds": age if age != float("inf") else None,
                "quote_valid": valid,
                "actual_contract_sizing": bool(actual_contract_sizing and lot > 0),
                "observed_at": datetime.now(timezone.utc).isoformat(),
            })
            if not valid:
                self.risk_violations += 1
        return len(self.observations)

    def record_closed_trade(self, trade):
        required = ("net_pnl", "fees", "slippage", "quantity", "entry_price", "exit_price")
        if any(key not in trade for key in required):
            raise ValueError("closed trade is missing required cost/size fields")
        quantity = int(trade["quantity"])
        entry = float(trade["entry_price"])
        exit_price = float(trade["exit_price"])
        if quantity <= 0 or entry <= 0 or exit_price <= 0:
            self.risk_violations += 1
            raise ValueError("invalid contract quantity or fill price")
        normalized = {
            "net_pnl": float(trade["net_pnl"]),
            "fees": max(0.0, float(trade["fees"])),
            "slippage": max(0.0, float(trade["slippage"])),
            "quantity": quantity,
            "entry_price": entry,
            "exit_price": exit_price,
            "market_id": str(trade.get("market_id", "")),
            "closed_at": str(trade.get("closed_at", datetime.now(timezone.utc).isoformat())),
        }
        self.trades.append(normalized)
        return normalized

    def record_risk_violation(self, reason):
        self.risk_violations += 1
        return {"risk_violation": str(reason), "count": self.risk_violations}

    def build(self, *, feed_label, portfolio_snapshots, duration_seconds=None):
        elapsed = (
            max(0.0, float(duration_seconds))
            if duration_seconds is not None
            else max(0.0, (datetime.now(timezone.utc) - self.started_at).total_seconds())
        )
        ages = [x["quote_age_seconds"] for x in self.observations if x["quote_age_seconds"] is not None]
        stale = sum(1 for x in self.observations if not x["quote_valid"])
        net_pnl = sum(x["net_pnl"] for x in self.trades)
        fees = sum(x["fees"] for x in self.trades)
        slippage = sum(x["slippage"] for x in self.trades)
        drawdowns = [
            float(s.get("drawdown_fraction", s.get("max_drawdown_fraction", 0.0)))
            for s in portfolio_snapshots
        ]
        max_drawdown = max(drawdowns, default=0.0)
        sizing_evidence = bool(self.observations) and all(
            x["actual_contract_sizing"] for x in self.observations
        )
        source_ok = str(feed_label).lower() in {"angelone-authorized", "angelone_mcx", "angelone_mcx_live_quotes"}
        checks = {
            "authorized_angelone_feed": source_ok,
            "quotes_observed": bool(self.observations),
            "all_quotes_fresh_and_valid": bool(self.observations) and stale == 0,
            "actual_contract_lot_sizes": sizing_evidence,
            "minimum_validation_duration": elapsed >= 3600,
            "minimum_closed_trades": len(self.trades) >= 3,
            "positive_net_pnl": net_pnl > 0,
            "drawdown_within_limit": 0 <= max_drawdown <= self.max_drawdown_fraction,
            "no_risk_violations": self.risk_violations == 0,
        }
        return {
            "feed_label": str(feed_label),
            "duration_seconds": round(elapsed, 3),
            "quote_observations": len(self.observations),
            "stale_or_invalid_quote_events": stale,
            "max_quote_age_seconds": max(ages, default=None),
            "closed_trades": len(self.trades),
            "net_pnl": round(net_pnl, 6),
            "fees": round(fees, 6),
            "slippage": round(slippage, 6),
            "max_drawdown_fraction": round(max_drawdown, 6),
            "risk_violations": self.risk_violations,
            "checks": checks,
            "passed": all(checks.values()),
            "live_orders_enabled": False,
            "operator_approval_required": True,
        }
