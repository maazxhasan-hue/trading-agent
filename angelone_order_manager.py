"""Fail-closed Angel One order lifecycle manager."""
from __future__ import annotations
import time


class OrderLifecycleError(RuntimeError):
    pass


class AngelOneOrderManager:
    def __init__(self, execution, journal=None, poll_seconds=2, timeout_seconds=20):
        self.execution = execution
        self.journal = journal
        self.poll_seconds = max(1, int(poll_seconds))
        self.timeout_seconds = max(1, int(timeout_seconds))

    def submit(self, request, intent_id):
        if not self.execution.enabled:
            raise OrderLifecycleError("live execution is disabled")
        existing = [
            order for order in self.execution.orders()
            if str(order.get("tag", "")) == str(intent_id)
        ]
        if existing:
            return self._result(existing[-1], allow_partial=True)

        order_id = self.execution.place_limit(request)
        if self.journal:
            self.journal.record("ORDER_SUBMITTED", order_id=order_id, intent_id=intent_id)

        deadline = time.time() + self.timeout_seconds
        last = None
        while time.time() < deadline:
            orders = self.execution.orders()
            last = next(
                (x for x in orders if str(x.get("order_id")) == str(order_id)),
                None,
            )
            if last:
                status = str(last.get("status", "")).upper()
                if status in {"COMPLETE", "TRADED"}:
                    return self._result(last)
                if status in {"REJECTED", "CANCELLED", "CANCELED", "EXPIRED"}:
                    raise OrderLifecycleError(
                        f"order {order_id} {status.lower()}: {last.get('text', '')}"
                    )
            time.sleep(self.poll_seconds)

        try:
            self.execution.cancel(order_id)
        except Exception:
            pass

        final = next(
            (x for x in self.execution.orders()
             if str(x.get("order_id")) == str(order_id)),
            None,
        )
        if final and int(final.get("filled_quantity", 0) or 0) > 0:
            return self._result(final, allow_partial=True)
        raise OrderLifecycleError(
            f"order {order_id} was not confirmed filled before timeout"
        )

    @staticmethod
    def _result(order, allow_partial=False):
        status = str(order.get("status", "")).upper()
        filled = int(order.get("filled_quantity", 0) or 0)
        requested = int(order.get("quantity", 0) or 0)
        if filled <= 0 or (status not in {"COMPLETE", "TRADED"} and not allow_partial):
            raise OrderLifecycleError(f"order {order.get('order_id')} not filled")
        return {
            "order_id": str(order.get("order_id")),
            "status": status,
            "requested_quantity": requested,
            "filled_quantity": filled,
            "pending_quantity": max(0, requested - filled),
            "average_price": float(order.get("average_price") or order.get("price") or 0),
            "tradingsymbol": order.get("tradingsymbol"),
            "transaction_type": order.get("transaction_type"),
        }
