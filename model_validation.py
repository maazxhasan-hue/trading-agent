"""Out-of-sample sanity validation for fair-value signals.

This is a safety gate, not a promise of predictive profit. It evaluates the
base fair-value model using only information available before each historical
next-price observation. It must pass before a researched candidate can reach
the trading decision stage.
"""
from dataclasses import dataclass
import math
import os
import statistics

from fair_value import FairValueModel


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    samples: int
    accuracy: float
    brier: float
    reason: str


def _clamp(x, lo=0.001, hi=0.999):
    return max(lo, min(hi, float(x)))


def validate_fair_value_history(
    prices,
    min_samples=None,
    min_accuracy=None,
    max_brier=None,
    min_move=None,
    lookback=None,
):
    min_samples = int(os.getenv("VALIDATION_MIN_SAMPLES", "30")) if min_samples is None else int(min_samples)
    min_accuracy = float(os.getenv("VALIDATION_MIN_ACCURACY", "0.55")) if min_accuracy is None else float(min_accuracy)
    max_brier = float(os.getenv("VALIDATION_MAX_BRIER", "0.25")) if max_brier is None else float(max_brier)
    min_move = float(os.getenv("VALIDATION_MIN_MOVE", "0.005")) if min_move is None else float(min_move)
    lookback = int(os.getenv("VALIDATION_LOOKBACK", "60")) if lookback is None else int(lookback)
    clean = []
    for value in prices or []:
        try:
            p = float(value)
        except (TypeError, ValueError):
            continue
        if 0.0 < p < 1.0 and math.isfinite(p):
            clean.append(p)

    if len(clean) < max(lookback + 2, min_samples + 2):
        return ValidationResult(False, 0, 0.0, 1.0, "insufficient_history")

    forecasts = []
    outcomes = []
    start = max(lookback, 1)
    for i in range(start, len(clean) - 1):
        current = clean[i]
        nxt = clean[i + 1]
        move = nxt - current
        if abs(move) < min_move:
            continue

        history = clean[max(0, i - lookback):i]
        if len(history) < 8:
            continue

        recent = history[-30:]
        mean = sum(recent) / len(recent)
        variance = sum((p - mean) ** 2 for p in recent) / len(recent)
        volatility = math.sqrt(variance)

        robust = statistics.median(history)
        result = FairValueModel().estimate(
            current=current,
            history_fair=robust,
            history_confidence=0.60,
            volatility=volatility,
            history=history,
        )
        forecasts.append(_clamp(result.value))
        outcomes.append(1.0 if move > 0 else 0.0)

    n = len(outcomes)
    if n < min_samples:
        return ValidationResult(False, n, 0.0, 1.0, "insufficient_out_of_sample_samples")

    correct = sum(
        int((p >= 0.5) == bool(y))
        for p, y in zip(forecasts, outcomes)
    )
    accuracy = correct / n
    brier = sum((p - y) ** 2 for p, y in zip(forecasts, outcomes)) / n

    passed = accuracy >= min_accuracy and brier <= max_brier
    if passed:
        reason = "validated"
    elif accuracy < min_accuracy:
        reason = "accuracy_below_threshold"
    else:
        reason = "brier_above_threshold"

    return ValidationResult(passed, n, accuracy, brier, reason)
