import pytest

from angelone_adapter import OrderRequest
from guarded_live_gate import GuardedLiveOrderGate, LiveOrderBlocked


def request(qty=1, price=5):
    return OrderRequest("GOLDM26OCTFUT", "123", "MCX", "BUY", qty, price, "CARRYFORWARD")


def evidence(**overrides):
    value = {
        "authorized_quote": True, "quote_age_seconds": 1,
        "contract_lot_size": 1, "actual_contract_quantity": True,
        "margin_verified": True, "required_margin": 100,
        "available_margin": 1000, "equity": 1000, "current_exposure": 0,
        "daily_pnl": 0, "peak_equity": 1000, "current_equity": 1000,
        "orders_today": 0, "market_open": True, "risk_checks_passed": True,
        "protective_exit_verified": True, "broker_reconciliation_healthy": True,
    }
    value.update(overrides)
    return value


def arm(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("LIVE_AUTONOMOUS_GUARDED_APPROVED", "true")
    monkeypatch.setenv("CLOUD_RUNTIME", "true")
    monkeypatch.setenv("LIVE_RUNTIME_APPROVED", "true")
    monkeypatch.setenv("LIVE_TRADING_ARM", "I_UNDERSTAND_LIVE_TRADING")
    monkeypatch.delenv("LIVE_KILL_SWITCH", raising=False)


def test_default_live_gate_blocks(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_TRADING", "false")
    gate = GuardedLiveOrderGate(str(tmp_path / "KILL"))
    with pytest.raises(LiveOrderBlocked, match="disabled"):
        gate.check(request(), "i-1", evidence())


def test_missing_evidence_blocks(monkeypatch, tmp_path):
    arm(monkeypatch)
    gate = GuardedLiveOrderGate(str(tmp_path / "KILL"))
    with pytest.raises(LiveOrderBlocked, match="evidence"):
        gate.check(request(), "i-1", None)


@pytest.mark.parametrize("override,match", [
    ({"quote_age_seconds": 99}, "stale"),
    ({"authorized_quote": False}, "authorized broker"),
    ({"contract_lot_size": 2}, "multiple"),
    ({"margin_verified": False}, "margin"),
    ({"available_margin": 10}, "insufficient"),
    ({"daily_pnl": -40}, "daily loss"),
    ({"current_equity": 800}, "drawdown"),
    ({"orders_today": 10}, "order-count"),
    ({"market_open": False}, "market_open"),
    ({"protective_exit_verified": False}, "protective_exit"),
    ({"broker_reconciliation_healthy": False}, "reconciliation"),
])
def test_each_failed_safety_gate_blocks(monkeypatch, tmp_path, override, match):
    arm(monkeypatch)
    gate = GuardedLiveOrderGate(str(tmp_path / "KILL"))
    with pytest.raises(LiveOrderBlocked, match=match):
        gate.check(request(), "i-1", evidence(**override))


def test_kill_switch_file_blocks(monkeypatch, tmp_path):
    arm(monkeypatch)
    kill = tmp_path / "KILL"
    kill.touch()
    gate = GuardedLiveOrderGate(str(kill))
    with pytest.raises(LiveOrderBlocked, match="kill switch"):
        gate.check(request(), "i-1", evidence())


def test_per_position_cap_blocks(monkeypatch, tmp_path):
    arm(monkeypatch)
    gate = GuardedLiveOrderGate(str(tmp_path / "KILL"))
    with pytest.raises(LiveOrderBlocked, match="per-position"):
        gate.check(request(qty=20, price=5), "i-1", evidence())


def test_duplicate_intent_blocks(monkeypatch, tmp_path):
    arm(monkeypatch)
    gate = GuardedLiveOrderGate(str(tmp_path / "KILL"))
    gate.check(request(), "i-1", evidence())
    gate.record_submitted("i-1")
    with pytest.raises(LiveOrderBlocked, match="duplicate"):
        gate.check(request(), "i-1", evidence())


@pytest.mark.parametrize("override", [
    {"equity": float("nan")},
    {"current_exposure": float("inf")},
    {"daily_pnl": float("-inf")},
    {"required_margin": float("nan")},
    {"available_margin": float("inf")},
    {"peak_equity": float("nan")},
    {"current_equity": float("inf")},
    {"orders_today": float("nan")},
    {"quote_age_seconds": float("nan")},
])
def test_non_finite_safety_values_always_block(monkeypatch, tmp_path, override):
    arm(monkeypatch)
    gate = GuardedLiveOrderGate(str(tmp_path / "KILL"))
    with pytest.raises(LiveOrderBlocked, match="finite"):
        gate.check(request(), "nonfinite", evidence(**override))


def test_non_finite_risk_limit_rejected_at_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("LIVE_MAX_POSITION_FRACTION", "nan")
    with pytest.raises(ValueError, match="finite and positive"):
        GuardedLiveOrderGate(str(tmp_path / "KILL"))


def test_fractional_order_count_blocks(monkeypatch, tmp_path):
    arm(monkeypatch)
    gate = GuardedLiveOrderGate(str(tmp_path / "KILL"))
    with pytest.raises(LiveOrderBlocked, match="must be integers"):
        gate.check(request(), "fractional-orders", evidence(orders_today=0.5))
