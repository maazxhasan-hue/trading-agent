"""Polymarket execution and reconciliation adapter.

Live execution is opt-in, cloud-only, and locked behind explicit runtime
approval plus protected credentials. Secrets are read only from the runtime
environment. A laptop/local checkout can never place live orders.
"""
import os
from dataclasses import dataclass

from runtime_guard import require_live_runtime


@dataclass
class LiveOrderRequest:
    token_id: str
    price: float
    size: float
    side: str


class LiveExecutionLocked(Exception):
    pass


class PolymarketExecution:
    def __init__(self):
        self.enabled = os.getenv("LIVE_TRADING", "false").lower() == "true"
        self.armed = os.getenv("LIVE_TRADING_ARM") == "I_UNDERSTAND_LIVE_TRADING"
        self.host = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
        self.client = None

        if self.enabled:
            if not self.armed:
                raise LiveExecutionLocked("LIVE_TRADING=true requires explicit arm.")
            try:
                require_live_runtime()
            except Exception as exc:
                raise LiveExecutionLocked(str(exc)) from exc
            self._connect()

    def _connect(self):
        try:
            from py_clob_client_v2 import ApiCreds, ClobClient
        except ImportError as exc:
            raise LiveExecutionLocked("Install py_clob_client_v2.") from exc
        required = ("PK", "CLOB_API_KEY", "CLOB_SECRET", "CLOB_PASS_PHRASE")
        missing = [x for x in required if not os.getenv(x)]
        if missing:
            raise LiveExecutionLocked("Missing live secret(s): " + ",".join(missing))
        self.client = ClobClient(
            host=self.host,
            chain_id=int(os.getenv("CHAIN_ID", "137")),
            key=os.environ["PK"],
            creds=ApiCreds(
                api_key=os.environ["CLOB_API_KEY"],
                api_secret=os.environ["CLOB_SECRET"],
                api_passphrase=os.environ["CLOB_PASS_PHRASE"],
            ),
        )

    def status(self):
        return {
            "live_enabled": self.enabled,
            "armed": self.armed,
            "cloud_runtime": os.getenv("CLOUD_RUNTIME", "false").lower() == "true",
            "live_runtime_approved": os.getenv("LIVE_RUNTIME_APPROVED", "false").lower() == "true",
            "connected": self.client is not None,
        }

    def cancel_all(self):
        if not self.enabled:
            return {"mode": "paper", "cancelled": 0}
        return self.client.cancel_all()

    def place_limit(self, request):
        if not self.enabled or not self.armed:
            raise LiveExecutionLocked("Live execution is locked.")
        try:
            require_live_runtime()
        except Exception as exc:
            raise LiveExecutionLocked(str(exc)) from exc

        from py_clob_client_v2 import OrderArgs, OrderType, PartialCreateOrderOptions, Side
        if not (0 < request.price < 1) or request.size <= 0:
            raise ValueError("Invalid live order price/size.")
        if request.side not in {"BUY", "SELL"}:
            raise ValueError("Side must be BUY or SELL.")
        response = self.client.create_and_post_order(
            order_args=OrderArgs(
                token_id=request.token_id,
                price=request.price,
                side=Side.BUY if request.side == "BUY" else Side.SELL,
                size=request.size,
            ),
            options=PartialCreateOrderOptions(
                tick_size=os.getenv("POLYMARKET_TICK_SIZE", "0.01")
            ),
            order_type=OrderType.GTC,
        )
        return response

    @staticmethod
    def order_id(response):
        if isinstance(response, dict):
            return response.get("orderID") or response.get("orderId") or response.get("id")
        return getattr(response, "orderID", None) or getattr(response, "orderId", None) or getattr(response, "id", None)

    def get_order(self, order_id):
        if not self.enabled:
            return None
        return self.client.get_order(order_id)

    def get_open_orders(self):
        if not self.enabled:
            return []
        return self.client.get_orders()

    def get_trades(self):
        if not self.enabled:
            return []
        return self.client.get_trades()

    def get_balance_allowance(self):
        if not self.enabled:
            return None
        from py_clob_client_v2 import BalanceAllowanceParams, AssetType
        return self.client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
