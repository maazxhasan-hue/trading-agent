"""Polymarket live execution adapter.

Live trading is opt-in and intentionally locked behind environment variables.
Secrets are read only from the runtime environment and never from repository files.
"""
import os
from dataclasses import dataclass


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

        if self.enabled and not self.armed:
            raise LiveExecutionLocked(
                "LIVE_TRADING=true requires LIVE_TRADING_ARM="
                "I_UNDERSTAND_LIVE_TRADING"
            )

        self.client = None
        if self.enabled:
            self._connect()

    def _connect(self):
        try:
            from py_clob_client_v2 import (
                ApiCreds,
                ClobClient,
            )
        except ImportError as exc:
            raise LiveExecutionLocked(
                "Install py_clob_client_v2 before enabling live execution."
            ) from exc

        key = os.environ["PK"]
        creds = ApiCreds(
            api_key=os.environ["CLOB_API_KEY"],
            api_secret=os.environ["CLOB_SECRET"],
            api_passphrase=os.environ["CLOB_PASS_PHRASE"],
        )
        chain_id = int(os.getenv("CHAIN_ID", "137"))
        self.client = ClobClient(
            host=self.host,
            chain_id=chain_id,
            key=key,
            creds=creds,
        )

    def status(self):
        return {
            "live_enabled": self.enabled,
            "armed": self.armed,
            "connected": self.client is not None,
        }

    def cancel_all(self):
        if not self.enabled:
            return {"mode": "paper", "cancelled": 0}
        return self.client.cancel_all()

    def place_limit(self, request: LiveOrderRequest):
        if not self.enabled or not self.armed:
            raise LiveExecutionLocked("Live execution is locked.")

        from py_clob_client_v2 import (
            OrderArgs,
            OrderType,
            PartialCreateOrderOptions,
            Side,
        )

        if not (0 < request.price < 1):
            raise ValueError("Price must be between 0 and 1.")
        if request.size <= 0:
            raise ValueError("Order size must be positive.")
        if request.side not in {"BUY", "SELL"}:
            raise ValueError("Side must be BUY or SELL.")

        side = Side.BUY if request.side == "BUY" else Side.SELL
        return self.client.create_and_post_order(
            order_args=OrderArgs(
                token_id=request.token_id,
                price=request.price,
                side=side,
                size=request.size,
            ),
            options=PartialCreateOrderOptions(
                tick_size=os.getenv("POLYMARKET_TICK_SIZE", "0.01")
            ),
            order_type=OrderType.GTC,
        )
