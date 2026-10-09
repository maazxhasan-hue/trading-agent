"""Isolated, paper-only portfolios for MCX tournament generations.

This module never imports a broker adapter and cannot place broker orders.
Each generation owns separate virtual cash and positions. If the configured
capital cannot afford one real contract lot within the notional cap, the
candidate is skipped rather than simulating fractional futures contracts.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


class MCXPaperPortfolioBook:
    """Small deterministic paper portfolio book, isolated by generation."""

    def __init__(
        self,
        path="data/mcx_gen_portfolios.json",
        starting_cash=100.0,
        max_position_fraction=0.06,
        max_total_exposure_fraction=0.30,
        slippage_bps=5.0,
        fee_bps=2.0,
        max_hold_cycles=12,
    ):
        self.path = path
        self.starting_cash = max(0.0, float(starting_cash))
        self.max_position_fraction = min(1.0, max(0.0, float(max_position_fraction)))
        self.max_total_exposure_fraction = min(1.0, max(0.0, float(max_total_exposure_fraction)))
        self.slippage_bps = max(0.0, float(slippage_bps))
        self.fee_bps = max(0.0, float(fee_bps))
        self.max_hold_cycles = max(1, int(max_hold_cycles))
        self.state = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and isinstance(data.get("portfolios"), dict):
                return data
        except (OSError, ValueError, TypeError):
            pass
        return {"portfolios": {}}

    def _save(self):
        parent = os.path.dirname(self.path) or "."
        os.makedirs(parent, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".mcx-portfolios-", suffix=".tmp", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.state, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def ensure_generation(self, generation):
        key = str(int(generation))
        if key not in self.state["portfolios"]:
            self.state["portfolios"][key] = {
                "generation": int(generation),
                "cash": self.starting_cash,
                "realized_pnl": 0.0,
                "positions": {},
                "closed_trades": [],
                "cycle": 0,
                "created_at": _now(),
            }
            self._save()
        return self.state["portfolios"][key]

    @staticmethod
    def _notional(position, price=None):
        return abs(float(price if price is not None else position["entry_price"]) * int(position["quantity"]))

    def _close(self, portfolio, market_id, price, reason):
        position = portfolio["positions"].pop(str(market_id), None)
        if not position:
            return None
        side_sign = 1 if position["direction"] > 0 else -1
        exit_price = float(price) * (1 - side_sign * self.slippage_bps / 10000.0)
        fill_pnl = (exit_price - float(position["entry_price"])) * int(position["quantity"]) * side_sign
        gross = (float(price) - float(position["reference_entry_price"])) * int(position["quantity"]) * side_sign
        entry_notional = self._notional(position)
        exit_notional = abs(exit_price * int(position["quantity"]))
        fees = (entry_notional + exit_notional) * self.fee_bps / 10000.0
        slippage = (
            abs(float(position["entry_price"]) - float(position["reference_entry_price"]))
            * int(position["quantity"])
            + abs(float(price) - exit_price) * int(position["quantity"])
        )
        net = gross - fees - slippage
        portfolio["cash"] += entry_notional + (fill_pnl - fees)
        portfolio["realized_pnl"] += net
        trade = {
            "generation": portfolio["generation"],
            "market_id": str(market_id),
            "tradingsymbol": position["tradingsymbol"],
            "direction": position["direction"],
            "quantity": int(position["quantity"]),
            "entry_price": float(position["entry_price"]),
            "exit_price": round(exit_price, 8),
            "gross_pnl": round(gross, 8),
            "fees": round(fees, 8),
            "slippage": round(slippage, 8),
            "net_pnl": round(net, 8),
            "reason": str(reason),
            "closed_at": _now(),
        }
        portfolio["closed_trades"].append(trade)
        portfolio["closed_trades"] = portfolio["closed_trades"][-5000:]
        return trade

    def process_snapshot(self, generation, market, signal):
        """Mark one quote and optionally act on a directional paper signal.

        market requires market_id, tradingsymbol, last_price, lot_size.
        signal is +1/-1/0 or a mapping with direction and optional stop_pct.
        Returns newly closed trades plus an auditable action status.
        """
        portfolio = self.ensure_generation(generation)
        portfolio["cycle"] += 1
        market_id = str(market["market_id"])
        price = float(market["last_price"])
        lot_size = max(1, int(market.get("lot_size", 1) or 1))
        if price <= 0:
            self._save()
            return {"opened": False, "reason": "invalid_price", "closed_trades": []}

        if isinstance(signal, dict):
            direction = int(signal.get("direction", 0))
            stop_pct = max(0.0, float(signal.get("stop_pct", 0.01)))
        else:
            direction, stop_pct = int(signal), 0.01
        direction = 1 if direction > 0 else -1 if direction < 0 else 0
        closed = []
        position = portfolio["positions"].get(market_id)
        if position:
            position["last_price"] = price
            side_sign = 1 if position["direction"] > 0 else -1
            move = (price / float(position["reference_entry_price"]) - 1.0) * side_sign
            held = portfolio["cycle"] - int(position["entry_cycle"])
            if move <= -float(position["stop_pct"]):
                trade = self._close(portfolio, market_id, price, "stop_loss")
                if trade:
                    closed.append(trade)
                position = None
            elif direction and direction != position["direction"]:
                trade = self._close(portfolio, market_id, price, "opposite_signal")
                if trade:
                    closed.append(trade)
                position = None
            elif held >= self.max_hold_cycles:
                trade = self._close(portfolio, market_id, price, "max_hold")
                if trade:
                    closed.append(trade)
                position = None

        opened = False
        reason = "no_signal"
        if position is None and direction:
            used = sum(self._notional(p) for p in portfolio["positions"].values())
            unrealized = 0.0
            for open_market_id, open_position in portfolio["positions"].items():
                mark = price if open_market_id == market_id else float(
                    open_position.get("last_price", open_position["reference_entry_price"])
                )
                sign = 1 if open_position["direction"] > 0 else -1
                unrealized += (mark - float(open_position["entry_price"])) * int(open_position["quantity"]) * sign
            # Equity includes reserved position notional and unrealized P&L; the
            # next 6% cap compounds from current equity, not the reduced free cash.
            equity = max(0.0, float(portfolio["cash"]) + used + unrealized)
            max_notional = min(
                equity * self.max_position_fraction,
                max(0.0, equity * self.max_total_exposure_fraction - used),
            )
            quantity = int(max_notional // (price * lot_size)) * lot_size
            if quantity <= 0:
                reason = "contract_lot_exceeds_position_cap"
            else:
                entry_price = price * (1 + direction * self.slippage_bps / 10000.0)
                notional = entry_price * quantity
                if notional > portfolio["cash"] or notional > max_notional * 1.01:
                    reason = "insufficient_virtual_cash_or_exposure"
                else:
                    portfolio["cash"] -= notional
                    portfolio["positions"][market_id] = {
                        "market_id": market_id,
                        "tradingsymbol": str(market.get("tradingsymbol", market_id)),
                        "direction": direction,
                        "quantity": quantity,
                        "entry_price": entry_price,
                        "reference_entry_price": price,
                        "last_price": price,
                        "entry_cycle": portfolio["cycle"],
                        "stop_pct": stop_pct,
                    }
                    opened, reason = True, "paper_position_opened"
        self._save()
        return {"opened": opened, "reason": reason, "closed_trades": closed}

    def close_generation(self, generation, prices, reason="generation_retired"):
        """Close all open virtual positions before retiring a candidate."""
        portfolio = self.ensure_generation(generation)
        closed = []
        for market_id in list(portfolio["positions"]):
            price = prices.get(market_id)
            if price is None or float(price) <= 0:
                # Fail closed: don't fabricate a fill for a missing/stale price.
                continue
            trade = self._close(portfolio, market_id, float(price), reason)
            if trade:
                closed.append(trade)
        self._save()
        return closed

    def snapshot(self, generation, prices=None):
        portfolio = self.ensure_generation(generation)
        prices = prices or {}
        unrealized = 0.0
        notional = 0.0
        for market_id, position in portfolio["positions"].items():
            price = float(prices.get(market_id, position["reference_entry_price"]))
            sign = 1 if position["direction"] > 0 else -1
            unrealized += (price - float(position["entry_price"])) * int(position["quantity"]) * sign
            notional += self._notional(position, price)
        return {
            "generation": int(generation),
            "cash": round(float(portfolio["cash"]), 4),
            "realized_pnl": round(float(portfolio["realized_pnl"]), 4),
            "unrealized_pnl": round(unrealized, 4),
            "equity": round(float(portfolio["cash"]) + notional + unrealized, 4),
            "open_positions": len(portfolio["positions"]),
            "closed_trades": len(portfolio["closed_trades"]),
            "live_orders_enabled": False,
        }
