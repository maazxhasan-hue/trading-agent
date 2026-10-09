"""Durable fail-closed risk-state storage for guarded live-order evidence.

This store does not calculate or invent risk metrics. An upstream, independently
verified source must provide every field. Snapshots are durable in SQLite and
rejected when stale, malformed, non-finite, or from a different trading day.
"""
from __future__ import annotations

import math
import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from angelone_live_evidence import LiveOrderEvidenceUnavailable

IST = ZoneInfo("Asia/Kolkata")
_REQUIRED_NUMERIC = (
    "equity", "current_exposure", "daily_pnl", "peak_equity",
    "current_equity", "orders_today",
)


def _finite_number(value, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise LiveOrderEvidenceUnavailable(f"risk field {field} is not numeric") from exc
    if not math.isfinite(result):
        raise LiveOrderEvidenceUnavailable(f"risk field {field} must be finite")
    return result


class DurableRiskStateStore:
    """SQLite-backed risk snapshot store with freshness and trading-day checks.

    Call record_snapshot only after an upstream component has verified the source
    and meaning of every value. The store itself is persistence, not evidence that
    the broker numbers are correct. Never pass fabricated/default values.
    """

    def __init__(
        self,
        path: str | os.PathLike = "data/live_risk_state.sqlite3",
        *,
        clock: Callable[[], float] = time.time,
        max_age_seconds: float = 30.0,
    ):
        self.path = Path(path)
        self.clock = clock
        self.max_age_seconds = float(max_age_seconds)
        if not math.isfinite(self.max_age_seconds) or self.max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be finite and positive")

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("""
            CREATE TABLE IF NOT EXISTS risk_snapshot (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                trading_day TEXT NOT NULL,
                captured_at REAL NOT NULL,
                equity REAL NOT NULL,
                current_exposure REAL NOT NULL,
                daily_pnl REAL NOT NULL,
                peak_equity REAL NOT NULL,
                current_equity REAL NOT NULL,
                orders_today INTEGER NOT NULL,
                checks_passed INTEGER NOT NULL,
                source TEXT NOT NULL
            )
        """)
        return connection

    @staticmethod
    def _trading_day(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp, IST).date().isoformat()

    def record_snapshot(self, snapshot: dict, *, source_verified: bool) -> None:
        if source_verified is not True:
            raise LiveOrderEvidenceUnavailable("risk snapshot source has not been independently verified")
        if not isinstance(snapshot, dict):
            raise LiveOrderEvidenceUnavailable("risk snapshot must be a mapping")
        missing = [key for key in (*_REQUIRED_NUMERIC, "checks_passed", "source") if key not in snapshot]
        if missing:
            raise LiveOrderEvidenceUnavailable("risk snapshot missing fields: " + ", ".join(missing))
        values = {key: _finite_number(snapshot[key], key) for key in _REQUIRED_NUMERIC}
        for field in ("equity", "peak_equity", "current_equity"):
            if values[field] <= 0:
                raise LiveOrderEvidenceUnavailable(f"risk field {field} must be positive")
        if values["current_exposure"] < 0:
            raise LiveOrderEvidenceUnavailable("risk current_exposure must not be negative")
        if values["orders_today"] < 0 or not values["orders_today"].is_integer():
            raise LiveOrderEvidenceUnavailable("risk orders_today must be a non-negative integer")
        if snapshot["checks_passed"] is not True:
            raise LiveOrderEvidenceUnavailable("independent risk checks have not passed")
        source = str(snapshot["source"]).strip()
        if not source or len(source) > 200:
            raise LiveOrderEvidenceUnavailable("risk snapshot source label is invalid")
        captured_at = self.clock()
        if not math.isfinite(captured_at):
            raise LiveOrderEvidenceUnavailable("risk snapshot clock is invalid")
        day = self._trading_day(captured_at)
        connection = self._connect()
        try:
            with connection:
                connection.execute("""
                    INSERT INTO risk_snapshot
                    (id, trading_day, captured_at, equity, current_exposure,
                     daily_pnl, peak_equity, current_equity, orders_today,
                     checks_passed, source)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      trading_day=excluded.trading_day,
                      captured_at=excluded.captured_at,
                      equity=excluded.equity,
                      current_exposure=excluded.current_exposure,
                      daily_pnl=excluded.daily_pnl,
                      peak_equity=excluded.peak_equity,
                      current_equity=excluded.current_equity,
                      orders_today=excluded.orders_today,
                      checks_passed=excluded.checks_passed,
                      source=excluded.source
                """, (
                    day, captured_at, values["equity"], values["current_exposure"],
                    values["daily_pnl"], values["peak_equity"], values["current_equity"],
                    int(values["orders_today"]), source,
                ))
        finally:
            connection.close()

    def __call__(self) -> dict:
        connection = self._connect()
        try:
            row = connection.execute("""
                SELECT trading_day, captured_at, equity, current_exposure, daily_pnl,
                       peak_equity, current_equity, orders_today, checks_passed, source
                FROM risk_snapshot WHERE id = 1
            """).fetchone()
        finally:
            connection.close()
        if row is None:
            raise LiveOrderEvidenceUnavailable("durable risk snapshot has not been recorded")
        day, captured_at, equity, exposure, pnl, peak, current, orders, checks, source = row
        now = self.clock()
        if not math.isfinite(now) or not math.isfinite(float(captured_at)):
            raise LiveOrderEvidenceUnavailable("durable risk snapshot timestamp is invalid")
        age = now - float(captured_at)
        if age < 0 or age > self.max_age_seconds:
            raise LiveOrderEvidenceUnavailable("durable risk snapshot is stale or from the future")
        if day != self._trading_day(now):
            raise LiveOrderEvidenceUnavailable("durable risk snapshot belongs to a different trading day")
        result = {
            "equity": equity,
            "current_exposure": exposure,
            "daily_pnl": pnl,
            "peak_equity": peak,
            "current_equity": current,
            "orders_today": orders,
            "checks_passed": checks == 1,
            "captured_at": captured_at,
            "age_seconds": age,
            "source": source,
        }
        # Revalidate stored data so corrupted DB values also fail closed.
        for key in _REQUIRED_NUMERIC:
            _finite_number(result[key], key)
        if result["checks_passed"] is not True:
            raise LiveOrderEvidenceUnavailable("stored risk checks are not passed")
        return result
