import math
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from angelone_live_evidence import LiveOrderEvidenceUnavailable
from durable_live_risk_state import DurableRiskStateStore


def base_snapshot(**overrides):
    result = {
        "equity": 100000,
        "current_exposure": 0.1,
        "daily_pnl": -100,
        "peak_equity": 105000,
        "current_equity": 99900,
        "orders_today": 2,
        "checks_passed": True,
        "source": "verified_broker_reconciliation",
    }
    result.update(overrides)
    return result


def test_store_round_trips_durable_snapshot(tmp_path):
    now = datetime(2026, 10, 9, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
    store = DurableRiskStateStore(tmp_path / "risk.sqlite3", clock=lambda: now)
    store.record_snapshot(base_snapshot(), source_verified=True)
    # A new instance reads the persisted snapshot, not in-memory state.
    result = DurableRiskStateStore(tmp_path / "risk.sqlite3", clock=lambda: now)()
    assert result["equity"] == 100000
    assert result["orders_today"] == 2
    assert result["checks_passed"] is True
    assert result["age_seconds"] == 0


def test_missing_snapshot_fails_closed(tmp_path):
    store = DurableRiskStateStore(tmp_path / "risk.sqlite3", clock=lambda: 1791547200)
    with pytest.raises(LiveOrderEvidenceUnavailable, match="has not been recorded"):
        store()


def test_unverified_source_cannot_be_persisted(tmp_path):
    store = DurableRiskStateStore(tmp_path / "risk.sqlite3")
    with pytest.raises(LiveOrderEvidenceUnavailable, match="not been independently verified"):
        store.record_snapshot(base_snapshot(), source_verified=False)


@pytest.mark.parametrize("field,value", [
    ("equity", float("nan")),
    ("current_exposure", float("inf")),
    ("daily_pnl", float("-inf")),
    ("peak_equity", 0),
    ("current_equity", -1),
    ("orders_today", 1.5),
])
def test_invalid_risk_values_fail_closed(tmp_path, field, value):
    store = DurableRiskStateStore(tmp_path / "risk.sqlite3")
    with pytest.raises(LiveOrderEvidenceUnavailable):
        store.record_snapshot(base_snapshot(**{field: value}), source_verified=True)


def test_stale_snapshot_fails_closed(tmp_path):
    now = datetime(2026, 10, 9, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
    clock = [now]
    store = DurableRiskStateStore(tmp_path / "risk.sqlite3", clock=lambda: clock[0], max_age_seconds=10)
    store.record_snapshot(base_snapshot(), source_verified=True)
    clock[0] += 11
    with pytest.raises(LiveOrderEvidenceUnavailable, match="stale"):
        store()


def test_future_snapshot_fails_closed(tmp_path):
    now = datetime(2026, 10, 9, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
    clock = [now]
    store = DurableRiskStateStore(tmp_path / "risk.sqlite3", clock=lambda: clock[0])
    store.record_snapshot(base_snapshot(), source_verified=True)
    clock[0] -= 1
    with pytest.raises(LiveOrderEvidenceUnavailable, match="future"):
        store()


def test_previous_trading_day_snapshot_fails_closed(tmp_path):
    day1 = datetime(2026, 10, 8, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
    day2 = datetime(2026, 10, 9, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp()
    clock = [day1]
    store = DurableRiskStateStore(tmp_path / "risk.sqlite3", clock=lambda: clock[0])
    store.record_snapshot(base_snapshot(), source_verified=True)
    clock[0] = day2
    with pytest.raises(LiveOrderEvidenceUnavailable, match="different trading day"):
        store()
