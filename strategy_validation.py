"""Chronological walk-forward validation for forecast-producing strategies.

Forecasts are generated before their outcomes are known, so each resolved
forecast is an out-of-sample observation. This module evaluates those
observations chronologically and adds stability checks before an agent can
become trading-eligible.
"""
from __future__ import annotations

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
