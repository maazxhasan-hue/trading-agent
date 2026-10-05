"""Persistent live portfolio ledger.

Tracks venue-confirmed fills separately from requested orders. It never invents
fills and treats the venue's matched quantity/average price as authoritative.
The ledger is intentionally small and JSON-backed so it survives container
restarts on Deplexo's /data volume.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone


def _state_path():
    return os.getenv(
        "LIVE_PORTFOLIO_FILE",
        "/data/live_portfolio.json" if os.path.isdir("/data") else "live_portfolio.json",
    )


@dataclass
class PositionLedger:
    market_id: str
    question: str
    side: str
    token_id: str
    requested_size: float = 0.0
    matched_size: float = 0.0
    average_fill_price: float = 0.0
    cost_basis: float = 0.0
    mark_price: float = 0.0
    updated_at: str = ""
    status: str = "OPEN"


class LivePortfolioLedger:
    def __init__(self, path=None):
        self.path = path or _state_path()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.positions = {}
        self.orders = {}
        self.realized_pnl = 0.0
        self.day_key = datetime.now(timezone.utc).date().isoformat()
        self._load()

    def _roll_day(self):
        today = datetime.now(timezone.utc).date().isoformat()
        if today != self.day_key:
            self.day_key = today
            self.realized_pnl = 0.0
            self._save()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            self.day_key = raw.get("day_key", self.day_key)
            self.realized_pnl = float(raw.get("realized_pnl", 0.0))
            self.positions = {
                k: PositionLedger(**v)
                for k, v in (raw.get("positions") or {}).items()
            }
            self.orders = raw.get("orders") or {}
            self._roll_day()
        except Exception:
            self.positions = {}
            self.orders = {}

    def _save(self):
        payload = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "day_key": self.day_key,
            "realized_pnl": self.realized_pnl,
            "positions": {k: asdict(v) for k, v in self.positions.items()},
            "orders": self.orders,
        }
        directory = os.path.dirname(self.path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".live_portfolio.", dir=directory, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def record_order(self, order_id, market_id, question, side, token_id,
                     requested_size, status="SUBMITTED"):
        if not order_id:
            return
        self.orders[str(order_id)] = {
            "market_id": str(market_id),
            "question": question,
            "side": side,
            "token_id": token_id,
            "requested_size": float(requested_size),
            "status": status,
            "updated_at": time.time(),
        }
        self._save()

    def reconcile_order(self, order_id, market_id, question, side, token_id,
                        requested_size, matched_size, average_price, status):
        """Apply cumulative venue state. Repeated snapshots are idempotent."""
        self._roll_day()
        oid = str(order_id)
        matched = max(0.0, float(matched_size or 0.0))
        avg = max(0.0, float(average_price or 0.0))
        requested = max(0.0, float(requested_size or 0.0))
        key = str(market_id)

        previous = self.positions.get(key)
        previous_matched = previous.matched_size if previous else 0.0
        previous_cost = previous.cost_basis if previous else 0.0

        if matched < previous_matched:
            # Never move a cumulative fill backwards.
            matched = previous_matched
        if matched > 0 and avg <= 0 and previous:
            avg = previous.average_fill_price

        if matched > 0:
            cost = matched * avg
            self.positions[key] = PositionLedger(
                market_id=key,
                question=question,
                side=side,
                token_id=token_id,
                requested_size=max(requested, previous.requested_size if previous else 0.0),
                matched_size=matched,
                average_fill_price=avg,
                cost_basis=cost,
                mark_price=previous.mark_price if previous else avg,
                updated_at=datetime.now(timezone.utc).isoformat(),
                status="OPEN",
            )
        elif previous is None:
            self.orders[oid] = {
                "market_id": key,
                "question": question,
                "side": side,
                "token_id": token_id,
                "requested_size": requested,
                "status": status,
                "updated_at": time.time(),
            }

        self.orders[oid] = {
            "market_id": key,
            "question": question,
            "side": side,
            "token_id": token_id,
            "requested_size": max(requested, self.orders.get(oid, {}).get("requested_size", 0.0)),
            "matched_size": matched,
            "average_fill_price": avg,
            "status": status,
            "updated_at": time.time(),
        }
        # 'previous_cost' is intentionally not booked as realized P&L here:
        # order status changes are not exits. Realized P&L requires a sell or
        # market settlement, which this BUY-only execution path does not yet
        # synthesize.
        self._save()

    def mark(self, market_id, mark_price):
        p = self.positions.get(str(market_id))
        if not p:
            return
        p.mark_price = max(0.0, float(mark_price))
        p.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()

    def remove_position(self, market_id, realized_pnl=None):
        key = str(market_id)
        if realized_pnl is not None:
            self._roll_day()
            self.realized_pnl += float(realized_pnl)
        self.positions.pop(key, None)
        self._save()

    def settle_position(self, market_id, payout_price):
        """Book realized P&L for a resolved position and remove it."""
        key = str(market_id)
        position = self.positions.get(key)
        if not position:
            return 0.0
        payout = max(0.0, min(1.0, float(payout_price)))
        pnl = position.matched_size * payout - position.cost_basis
        self._roll_day()
        self.realized_pnl += pnl
        self.positions.pop(key, None)
        self._save()
        return pnl

    def unrealized_pnl(self):
        total = 0.0
        for p in self.positions.values():
            if p.matched_size <= 0 or p.mark_price <= 0:
                continue
            total += p.matched_size * p.mark_price - p.cost_basis
        return total

    def total_exposure(self, bankroll):
        if bankroll <= 0:
            return 0.0
        return sum(p.cost_basis for p in self.positions.values()) / bankroll

    def daily_pnl(self):
        self._roll_day()
        return self.realized_pnl + self.unrealized_pnl()

    def snapshot(self):
        return {
            "positions": len(self.positions),
            "realized_pnl": round(self.realized_pnl, 8),
            "unrealized_pnl": round(self.unrealized_pnl(), 8),
            "daily_pnl": round(self.daily_pnl(), 8),
            "exposure_cost": round(sum(p.cost_basis for p in self.positions.values()), 8),
        }
