"""Production-oriented live order reconciliation helpers.

The venue is the source of truth: this module never invents fills. It normalizes
common CLOB order fields, tracks cumulative fills, and identifies terminal
states so the engine can safely reconcile partial fills and cancellations.
"""
from dataclasses import dataclass

TERMINAL = {"CANCELED", "CANCELLED", "REJECTED", "FILLED", "EXPIRED"}


@dataclass
class FillState:
    order_id: str
    status: str
    requested_size: float
    matched_size: float
    remaining_size: float
    average_price: float | None
    raw: dict


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_order(order_id, state):
    state = state or {}
    requested = _num(
        state.get("original_size",
                  state.get("size", state.get("originalSize")))
    )
    matched = _num(
        state.get("size_matched",
                  state.get("sizeMatched",
                             state.get("matched_size")))
    )
    remaining_raw = state.get(
        "size_remaining", state.get("sizeRemaining")
    )
    remaining = (
        max(0.0, requested - matched)
        if requested
        else _num(remaining_raw)
    )
    if remaining_raw not in (None, ""):
        remaining = max(0.0, _num(remaining_raw))
    average = state.get("average_price", state.get("avgPrice"))
    average_price = (
        _num(average, None) if average not in (None, "") else None
    )
    status = str(state.get("status", "UNKNOWN")).upper()
    return FillState(
        str(order_id), status, requested, matched, remaining,
        average_price, state
    )


def is_terminal(fill):
    return fill.status in TERMINAL


def has_new_fill(previous, current):
    if previous is None:
        return current.matched_size > 0
    return current.matched_size > previous.matched_size
