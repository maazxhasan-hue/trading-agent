"""Fail-closed Zerodha order lifecycle helper.

The manager never assumes a submitted order is filled. It records an intent,
checks broker status, handles partial fills, and can cancel an unfilled order.
It does not enable live trading by itself.
"""
from __future__ import annotations
import time

class OrderLifecycleError(RuntimeError):
    pass

class ZerodhaOrderManager:
    def __init__(self, execution, journal=None, poll_seconds=2, timeout_seconds=20):
        self.execution=execution
        self.journal=journal
        self.poll_seconds=max(1,int(poll_seconds))
        self.timeout_seconds=max(1,int(timeout_seconds))

    @staticmethod
    def _status(order):
        return str(order.get("status","")).upper()

    def _find(self, order_id):
        for order in self.execution.orders():
            if str(order.get("order_id"))==str(order_id):
                return order
        return None

    def submit(self, request, intent_id):
        if not self.execution.enabled:
            raise OrderLifecycleError("live execution is disabled")
        existing=[]
        for order in self.execution.orders():
            if str(order.get("tag",""))==str(intent_id):
                existing.append(order)
        if existing:
            order=existing[-1]
            return self._result(order)

        order_id=self.execution.place_limit(request)
        if self.journal:
            self.journal.record("ORDER_SUBMITTED",order_id=order_id,intent_id=intent_id)
        deadline=time.time()+self.timeout_seconds
        last=None
        while time.time()<deadline:
            last=self._find(order_id)
            if last:
                status=self._status(last)
                if status=="COMPLETE":
                    return self._result(last)
                if status in {"REJECTED","CANCELLED"}:
                    raise OrderLifecycleError(f"order {order_id} {status.lower()}")
            time.sleep(self.poll_seconds)
        try:
            self.execution.cancel(order_id)
        except Exception:
            pass
        final=self._find(order_id)
        if final:
            filled=int(final.get("filled_quantity",0) or 0)
            if filled>0:
                result=self._result(final, allow_partial=True)
                if self.journal:
                    self.journal.record("ORDER_PARTIAL_FILL", order_id=order_id, filled_quantity=filled)
                return result
        raise OrderLifecycleError(f"order {order_id} not confirmed filled before timeout")

    def _result(self, order, allow_partial=False):
        status=self._status(order)
        filled=int(order.get("filled_quantity",0) or 0)
        requested=int(order.get("quantity",0) or 0)
        pending=max(0,requested-filled)
        if filled<=0 or (status!="COMPLETE" and not allow_partial):
            raise OrderLifecycleError(f"order {order.get('order_id')} not filled")
        return {
            "order_id":str(order.get("order_id")),
            "status":status,
            "requested_quantity":int(order.get("quantity",0) or 0),
            "filled_quantity":filled,
            "pending_quantity":pending,
            "average_price":float(order.get("average_price") or order.get("price") or 0),
            "tradingsymbol":order.get("tradingsymbol"),
            "transaction_type":order.get("transaction_type"),
        }
