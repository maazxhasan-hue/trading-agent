"""Chronological walk-forward validation for forecast-producing strategies.

Forecasts are generated before their outcomes are known, so each resolved
forecast is an out-of-sample observation. This module evaluates those
observations chronologically and adds stability checks before an agent can
become trading-eligible.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ValidationWindow:
    train_samples: int
    test_samples: int
    correct: int
    accuracy: float
    brier: float


def _agent_rows(history: Iterable[dict], agent_id: str) -> list[dict]:
    rows = []
    for item in history:
        outcome = item.get("outcome")
        directions = item.get("directions") or {}
        if outcome not in (-1, 1) or agent_id not in directions:
            continue
        direction = int(directions[agent_id])
        if direction not in (-1, 1):
            continue
        confidence = min(0.95, max(0.50, float(item.get("confidence", 0.5))))
        resolved_at = float(item.get("resolved_at", item.get("created_at", 0.0)))
        rows.append({
            "time": resolved_at,
            "correct": direction == int(outcome),
            "brier": (confidence - (1.0 if direction == int(outcome) else 0.0)) ** 2,
        })
    rows.sort(key=lambda row: row["time"])
    return rows


def walk_forward_report(
    history: Iterable[dict],
    agent_id: str,
    *,
    test_size: int = 10,
    min_train_samples: int = 10,
    min_windows: int = 2,
    recent_size: int = 10,
    min_recent_accuracy: float = 0.50,
    max_recent_accuracy_drop: float = 0.15,
    min_accuracy: float = 0.55,
    max_brier: float = 0.25,
) -> dict:
    """Evaluate one agent using chronological holdout windows.

    No future observations are used to score an earlier window. The first
    window is held out until at least min_train_samples exist; the training
    count is reported for auditability, but no fitting is performed here.
    """
    rows = _agent_rows(history, agent_id)
    n = len(rows)
    if n == 0:
        return {
            "samples": 0,
            "accuracy": None,
            "brier": None,
            "recent_accuracy": None,
            "recent_brier": None,
            "windows": [],
            "walk_forward_samples": 0,
            "walk_forward_accuracy": None,
            "walk_forward_brier": None,
            "walk_forward_windows": 0,
            "recent_stable": False,
            "status": "insufficient_samples",
        }

    accuracy = sum(r["correct"] for r in rows) / n
    brier = sum(r["brier"] for r in rows) / n
    recent = rows[-max(1, recent_size):]
    recent_accuracy = sum(r["correct"] for r in recent) / len(recent)
    recent_brier = sum(r["brier"] for r in recent) / len(recent)

    windows: list[ValidationWindow] = []
    start = max(0, min_train_samples)
    while start < n:
        test = rows[start:start + max(1, test_size)]
        if len(test) < max(1, test_size):
            break
        correct = sum(r["correct"] for r in test)
        windows.append(
            ValidationWindow(
                train_samples=start,
                test_samples=len(test),
                correct=correct,
                accuracy=correct / len(test),
                brier=sum(r["brier"] for r in test) / len(test),
            )
        )
        start += max(1, test_size)

    wf_n = sum(w.test_samples for w in windows)
    wf_accuracy = (
        sum(w.correct for w in windows) / wf_n if wf_n else None
    )
    wf_brier = (
        sum(w.brier * w.test_samples for w in windows) / wf_n
        if wf_n else None
    )
    required_windows = max(1, min_windows)
    recent_stable = (
        recent_accuracy >= min_recent_accuracy
        and recent_accuracy >= accuracy - max_recent_accuracy_drop
    )

    status = "validated" if (
        n >= min_train_samples + required_windows * max(1, test_size)
        and len(windows) >= required_windows
        and accuracy >= min_accuracy
        and brier <= max_brier
        and wf_accuracy is not None
        and wf_brier is not None
        and wf_accuracy >= min_accuracy
        and wf_brier <= max_brier
        and recent_stable
    ) else "insufficient_or_unstable"

    return {
        "samples": n,
        "accuracy": accuracy,
        "brier": brier,
        "recent_accuracy": recent_accuracy,
        "recent_brier": recent_brier,
        "windows": [w.__dict__ for w in windows],
        "walk_forward_samples": wf_n,
        "walk_forward_accuracy": wf_accuracy,
        "walk_forward_brier": wf_brier,
        "walk_forward_windows": len(windows),
        "recent_stable": recent_stable,
        "status": status,
    }


_ECONOMIC_COSTS = ("fees", "spread", "slippage", "taxes")
_FILLED_STATES = {"FILLED", "PARTIALLY_FILLED", "COMPLETE", "TRADED"}
_UNFILLED_STATES = {"REJECTED", "CANCELLED", "CANCELED", "UNFILLED", "EXPIRED"}


def _economic_rows(history: Iterable[dict], strategy_id: str):
    rows = []
    costs_incomplete = False
    invalid_data = False
    missing_regime = False
    for item in history or ():
        if not isinstance(item, dict):
            invalid_data = True
            continue
        if item.get("strategy_id") != strategy_id:
            continue
        try:
            timestamp = float(item["timestamp"])
            if not math.isfinite(timestamp):
                raise ValueError
            status = str(item.get("status", "")).strip().upper()
            if status not in _FILLED_STATES | _UNFILLED_STATES:
                raise ValueError
            is_filled = status in _FILLED_STATES
            gross = float(item.get("gross_pnl", 0.0))
            turnover = float(item.get("turnover", 0.0))
            if not math.isfinite(gross) or not math.isfinite(turnover) or turnover < 0:
                raise ValueError
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid_data = True
            continue

        regime_value = item.get("regime")
        if (
            not isinstance(regime_value, str)
            or not regime_value.strip()
            or regime_value.strip().upper() == "UNKNOWN"
        ):
            missing_regime = True
        supplied_costs = item.get("costs")
        if not isinstance(supplied_costs, dict) or any(key not in supplied_costs for key in _ECONOMIC_COSTS):
            costs_incomplete = True
            gross = gross if is_filled else 0.0
            rows.append({
                "timestamp": timestamp,
                "status": status,
                "filled": is_filled,
                "gross_pnl": gross,
                "costs": None,
                "net_pnl": None,
                "turnover": turnover if is_filled else 0.0,
                "regime": str(item.get("regime") or "UNKNOWN").strip().upper() or "UNKNOWN",
            })
            continue
        try:
            costs = {key: float(supplied_costs[key]) for key in _ECONOMIC_COSTS}
            if any(not math.isfinite(value) or value < 0 for value in costs.values()):
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            costs_incomplete = True
            gross = gross if is_filled else 0.0
            rows.append({
                "timestamp": timestamp,
                "status": status,
                "filled": is_filled,
                "gross_pnl": gross,
                "costs": None,
                "net_pnl": None,
                "turnover": turnover if is_filled else 0.0,
                "regime": str(item.get("regime") or "UNKNOWN").strip().upper() or "UNKNOWN",
            })
            continue

        regime = str(item.get("regime") or "UNKNOWN").strip().upper()
        if not regime:
            regime = "UNKNOWN"
        gross = gross if is_filled else 0.0
        rows.append({
            "timestamp": timestamp,
            "status": status,
            "filled": is_filled,
            "gross_pnl": gross,
            "costs": costs,
            "net_pnl": gross - sum(costs.values()),
            "turnover": turnover if is_filled else 0.0,
            "regime": regime,
        })
    rows.sort(key=lambda row: row["timestamp"])
    return rows, costs_incomplete, invalid_data, missing_regime


def _economic_totals(rows):
    gross = sum(row["gross_pnl"] for row in rows)
    costs = {
        name: sum(row["costs"][name] for row in rows)
        for name in _ECONOMIC_COSTS
    }
    net = gross - sum(costs.values())
    return {
        "gross_pnl": gross,
        "costs": costs,
        "total_costs": sum(costs.values()),
        "net_pnl": net,
        "trade_count": sum(row["filled"] for row in rows),
        "rejected_count": sum(not row["filled"] for row in rows),
        "turnover": sum(row["turnover"] for row in rows),
        "expectancy": net / sum(row["filled"] for row in rows) if any(row["filled"] for row in rows) else None,
    }


def net_walk_forward_report(
    history: Iterable[dict],
    *,
    strategy_id: str,
    baseline_trades: Iterable[dict] | None,
    test_size: int = 10,
    min_train_samples: int = 10,
    min_windows: int = 2,
    min_regime_samples: int = 5,
    benchmark_per_hour: float = 1000.0,
    starting_capital: float | None = None,
) -> dict:
    """Report economic performance on chronological holdout trades.

    Inputs are realized trade records. Each row must identify execution status,
    gross realized P&L, turnover, regime, timestamp, and round-trip fees/spread/
    slippage/taxes. Missing costs make the entire report ineligible. Rejected
    orders contribute no invented gross P&L and remain visible in counts.
    Positive output can qualify a strategy for further paper evaluation only.
    """
    benchmark = float(benchmark_per_hour)
    if not math.isfinite(benchmark) or benchmark < 0:
        raise ValueError("benchmark_per_hour must be finite and nonnegative")
    if type(test_size) is not int or test_size <= 0:
        raise ValueError("test_size must be a positive integer")
    if type(min_train_samples) is not int or min_train_samples < 0:
        raise ValueError("min_train_samples must be a nonnegative integer")
    if type(min_windows) is not int or min_windows <= 0:
        raise ValueError("min_windows must be a positive integer")
    if type(min_regime_samples) is not int or min_regime_samples <= 0:
        raise ValueError("min_regime_samples must be a positive integer")
    if starting_capital is not None and (
        not math.isfinite(float(starting_capital)) or float(starting_capital) <= 0
    ):
        raise ValueError("starting_capital must be finite and positive")

    rows, costs_incomplete, invalid_data, missing_regime = _economic_rows(history, strategy_id)
    baseline_rows, baseline_costs_incomplete, baseline_invalid, baseline_missing_regime = (
        _economic_rows(baseline_trades, "baseline") if baseline_trades is not None
        else ([], False, False, False)
    )
    if invalid_data or costs_incomplete:
        status = "INVALID_DATA" if invalid_data else "COSTS_INCOMPLETE"
        report_identity = {
            "strategy_id": strategy_id,
            "rows": rows,
            "status": status,
        }
        version = hashlib.sha256(
            json.dumps(report_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        return {
            "strategy_id": strategy_id,
            "validation_version": "cost-wf-" + version,
            "status": status,
            "paper_only_qualified": False,
            "live_eligible": False,
            "samples": len(rows),
            "walk_forward_windows": 0,
            "walk_forward_samples": 0,
            "windows": [],
            "regimes": {},
            "gross_pnl": None,
            "costs": None,
            "total_costs": None,
            "net_pnl": None,
            "trade_count": sum(row["filled"] for row in rows),
            "rejected_count": sum(not row["filled"] for row in rows),
            "turnover": None,
            "expectancy": None,
            "drawdown": None,
            "drawdown_fraction": None,
            "hourly_net_pnl": None,
            "target_pnl_per_hour": benchmark,
            "target_gap_per_hour": None,
            "benchmark_status": "RESEARCH_ONLY",
            "baseline_net_pnl": None,
            "baseline_delta": None,
        }
    start = min_train_samples
    windows = []
    holdout_rows = []
    while start + test_size <= len(rows):
        test = rows[start:start + test_size]
        start_time, end_time = test[0]["timestamp"], test[-1]["timestamp"]
        windows.append({
            "train_samples": start,
            "test_start": start_time,
            "test_end": end_time,
            "test_samples": len(test),
            **_economic_totals(test),
        })
        holdout_rows.extend(test)
        start += test_size

    metrics = _economic_totals(holdout_rows)
    n = len(rows)
    required_samples = min_train_samples + min_windows * test_size
    evaluated_limit = min(
        len(rows), min_train_samples + len(windows) * test_size
    )
    valid_sample_count = sum(row["filled"] for row in rows[:evaluated_limit])
    windows_complete = len(windows) >= min_windows and len(holdout_rows) >= min_windows * test_size
    regime_rows = {}
    for row in holdout_rows:
        regime_rows.setdefault(row["regime"], []).append(row)
    regimes = {
        name: _economic_totals(regime)
        for name, regime in sorted(regime_rows.items())
    }
    qualified_regimes = [
        metrics_for_regime for metrics_for_regime in regimes.values()
        if metrics_for_regime["trade_count"] >= min_regime_samples
    ]

    drawdown = None
    drawdown_fraction = None
    if holdout_rows:
        equity = peak = max_drawdown = 0.0
        for row in holdout_rows:
            equity += row["net_pnl"]
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)
        drawdown = max_drawdown
        if starting_capital is not None:
            drawdown_fraction = max_drawdown / float(starting_capital)

    duration = (
        holdout_rows[-1]["timestamp"] - holdout_rows[0]["timestamp"]
        if len(holdout_rows) > 1 else 0.0
    )
    hourly_net = metrics["net_pnl"] / (duration / 3600.0) if duration > 0 else None
    benchmark_gap = benchmark - hourly_net if hourly_net is not None else None

    baseline_test_rows = []
    baseline_rows_by_window = []
    for window in windows:
        window_baseline = [
            row for row in baseline_rows
            if window["test_start"] <= row["timestamp"] <= window["test_end"]
        ]
        baseline_rows_by_window.append(window_baseline)
        baseline_test_rows.extend(window_baseline)
    baseline_coverage_sufficient = bool(windows) and all(
        len(rows_for_window) >= window["test_samples"]
        for window, rows_for_window in zip(windows, baseline_rows_by_window)
    )
    baseline_metrics = (
        _economic_totals(baseline_test_rows)
        if baseline_test_rows and not baseline_costs_incomplete
        else None
    )
    baseline_delta = (
        metrics["net_pnl"] - baseline_metrics["net_pnl"]
        if baseline_metrics else None
    )

    if invalid_data or baseline_invalid:
        status = "INVALID_DATA"
    elif missing_regime:
        status = "MISSING_REGIME_LABEL"
    elif baseline_costs_incomplete:
        status = "BASELINE_COSTS_INCOMPLETE"
    elif baseline_missing_regime:
        status = "BASELINE_REGIME_MISSING"
    elif valid_sample_count < required_samples or not windows_complete or metrics["trade_count"] == 0:
        status = "INSUFFICIENT_SAMPLES"
    elif metrics["net_pnl"] <= 0:
        status = "NEGATIVE_NET_AFTER_COSTS"
    elif len(qualified_regimes) != len(regimes):
        status = "INSUFFICIENT_REGIME_SAMPLES"
    elif any(item["net_pnl"] <= 0 for item in qualified_regimes):
        status = "UNSTABLE_BY_REGIME"
    elif baseline_test_rows and not baseline_coverage_sufficient:
        status = "BASELINE_INSUFFICIENT_SAMPLES"
    elif baseline_metrics is None:
        status = "BASELINE_MISSING"
    elif baseline_delta < 0:
        status = "BELOW_BASELINE"
    else:
        status = "PAPER_ONLY_POSITIVE_AFTER_COSTS"

    report_identity = {
        "strategy_id": strategy_id,
        "rows": rows,
        "baseline_rows": baseline_rows,
        "test_size": test_size,
        "min_train_samples": min_train_samples,
        "min_windows": min_windows,
        "min_regime_samples": min_regime_samples,
    }
    version = hashlib.sha256(
        json.dumps(report_identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "strategy_id": strategy_id,
        "validation_version": "cost-wf-" + version,
        "status": status,
        "paper_only_qualified": status == "PAPER_ONLY_POSITIVE_AFTER_COSTS",
        "live_eligible": False,
        "samples": n,
        "walk_forward_windows": len(windows),
        "walk_forward_samples": len(holdout_rows),
        "windows": windows,
        "regimes": regimes,
        **metrics,
        "drawdown": drawdown,
        "drawdown_fraction": drawdown_fraction,
        "hourly_net_pnl": hourly_net,
        "target_pnl_per_hour": benchmark,
        "target_gap_per_hour": benchmark_gap,
        "benchmark_status": "RESEARCH_ONLY",
        "baseline_net_pnl": baseline_metrics["net_pnl"] if baseline_metrics else None,
        "baseline_delta": baseline_delta,
    }

