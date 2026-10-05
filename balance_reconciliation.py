"""Cloud-safe collateral/balance reconciliation for Polymarket.

The venue is authoritative. The engine never treats requested orders as spent
capital until the venue confirms the order/fill state. Unknown balance payloads
fail closed instead of guessing.
"""

from __future__ import annotations

from typing import Any


def _number(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_available_collateral(payload: Any):
    """Extract a conservative available collateral amount.

    Supports common dict/object response shapes while rejecting ambiguous data.
    Returns None when no trustworthy numeric collateral field can be identified.
    """
    if payload is None:
        return None

    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        return float(payload)

    if isinstance(payload, dict):
        # Prefer explicitly available/free/allowance fields. Do not interpret
        # an arbitrary total balance as spendable collateral.
        preferred = (
            "available", "available_balance", "availableBalance",
            "free", "free_balance", "freeBalance",
            "collateral_available", "collateralAvailable",
        )
        for key in preferred:
            value = _number(payload.get(key))
            if value is not None and value >= 0:
                return value
        for key in ("balance", "balance_allowance"):
            nested = payload.get(key)
            value = extract_available_collateral(nested)
            if value is not None:
                return value
        for key in ("data", "result"):
            nested = payload.get(key)
            value = extract_available_collateral(nested)
            if value is not None:
                return value

    for key in (
        "available", "available_balance", "availableBalance",
        "free", "free_balance", "freeBalance",
    ):
        value = _number(getattr(payload, key, None))
        if value is not None and value >= 0:
            return value

    return None


def collateral_sufficient(available, required, reserve_fraction=0.10):
    """Require a reserve and fail closed on unknown balances."""
    available = _number(available)
    required = _number(required)
    reserve_fraction = max(0.0, min(0.50, float(reserve_fraction)))
    if available is None or required is None or required < 0:
        return False
    return available * (1.0 - reserve_fraction) >= required
