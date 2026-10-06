"""Non-invasive broker reconciliation helpers.

These functions compare intended orders/positions with broker-reported state.
They never place, modify, or cancel orders.
"""
from __future__ import annotations


TERMINAL_ORDER_STATUSES = {
    "COMPLETE",
    "CANCELLED",
    "REJECTED",
    "EXPIRED",
}


def open_broker_orders(orders):
    return [
        order for order in orders or []
        if str(order.get("status", "")).upper() not in TERMINAL_ORDER_STATUSES
    ]


def normalize_positions(positions):
    result = {}
    for position in positions or []:
        symbol = str(position.get("tradingsymbol", "")).upper()
        if not symbol:
            continue
        quantity = int(position.get("quantity", 0) or 0)
        if quantity:
            result[symbol] = {
                "quantity": quantity,
                "average_price": float(position.get("average_price", 0) or 0),
                "product": position.get("product"),
                "exchange": position.get("exchange"),
            }
    return result


def reconcile(intended_positions, broker_positions, broker_orders):
    """Return differences; caller decides what, if anything, to do."""
    intended = normalize_positions(intended_positions)
    broker = normalize_positions(broker_positions)
    symbols = sorted(set(intended) | set(broker))

    position_mismatches = []
    for symbol in symbols:
        expected_qty = intended.get(symbol, {}).get("quantity", 0)
        actual_qty = broker.get(symbol, {}).get("quantity", 0)
        if expected_qty != actual_qty:
            position_mismatches.append({
                "symbol": symbol,
                "expected_quantity": expected_qty,
                "broker_quantity": actual_qty,
            })

    return {
        "in_sync": not position_mismatches and not open_broker_orders(broker_orders),
        "position_mismatches": position_mismatches,
        "open_orders": open_broker_orders(broker_orders),
    }
