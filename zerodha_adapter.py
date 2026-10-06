"""Production Zerodha Kite Connect adapter.

Live orders are opt-in and remain disabled until all runtime gates pass.
Credentials are read only from environment variables; never commit them.
"""
import os
from dataclasses import dataclass

try:
    from kiteconnect import KiteConnect
except ImportError:
    KiteConnect = None


class ZerodhaLocked(RuntimeError):
    pass


@dataclass
class OrderRequest:
    tradingsymbol: str
    exchange: str
    transaction_type: str
    quantity: int
    price: float
    product: str = "MIS"
    tag: str | None = None


class ZerodhaExecution:
    def __init__(self):
        self.enabled = os.getenv("LIVE_TRADING", "false").lower() == "true"
        self.armed = os.getenv("LIVE_TRADING_ARM") == "I_UNDERSTAND_LIVE_TRADING"
        self.api_key = os.getenv("KITE_API_KEY", "")
        self.access_token = os.getenv("KITE_ACCESS_TOKEN", "")
        self.client = None
        if self.enabled:
            self._connect()

    def _connect(self):
        if not self.armed:
            raise ZerodhaLocked("LIVE_TRADING=true requires LIVE_TRADING_ARM.")
        if os.getenv("CLOUD_RUNTIME", "false").lower() != "true":
            raise ZerodhaLocked("Live Zerodha execution is allowed only in the cloud runtime.")
        if os.getenv("LIVE_RUNTIME_APPROVED", "false").lower() != "true":
            raise ZerodhaLocked("LIVE_RUNTIME_APPROVED=true is required for live execution.")
        if not self.api_key or not self.access_token:
            raise ZerodhaLocked("KITE_API_KEY and KITE_ACCESS_TOKEN are required.")
        if KiteConnect is None:
            raise ZerodhaLocked("Install kiteconnect before enabling live execution.")
        self.client = KiteConnect(api_key=self.api_key)
        self.client.set_access_token(self.access_token)
        self.client.profile()

    def status(self):
        return {
            "broker": "zerodha",
            "live_enabled": self.enabled,
            "armed": self.armed,
            "cloud_runtime": os.getenv("CLOUD_RUNTIME", "false").lower() == "true",
            "live_runtime_approved": os.getenv("LIVE_RUNTIME_APPROVED", "false").lower() == "true",
            "connected": self.client is not None,
        }

    def instruments(self, exchange="NSE"):
        if self.client is None:
            return []
        return self.client.instruments(exchange)

    def quote(self, instruments):
        if self.client is None:
            return {}
        return self.client.quote(instruments)

    def historical(self, instrument_token, from_date, to_date, interval="5minute"):
        if self.client is None:
            return []
        return self.client.historical_data(
            instrument_token=int(instrument_token),
            from_date=from_date,
            to_date=to_date,
            interval=interval,
        )

    def place_limit(self, request: OrderRequest):
        if self.client is None:
            raise ZerodhaLocked("Live execution is disabled; use paper mode.")
        if request.quantity <= 0 or request.price <= 0:
            raise ValueError("Invalid quantity/price")
        if request.transaction_type not in {"BUY", "SELL"}:
            raise ValueError("Invalid transaction type")
        kwargs = {
            "variety": self.client.VARIETY_REGULAR,
            "exchange": request.exchange,
            "tradingsymbol": request.tradingsymbol,
            "transaction_type": request.transaction_type,
            "quantity": int(request.quantity),
            "product": request.product,
            "order_type": self.client.ORDER_TYPE_LIMIT,
            "price": float(request.price),
            "validity": self.client.VALIDITY_DAY,
        }
        if request.tag:
            kwargs["tag"] = request.tag
        return self.client.place_order(**kwargs)

    def funds_available(self):
        if not self.client:
            return None
        data = self.client.margins("equity")
        available = data.get("available", {}) if isinstance(data, dict) else {}
        for key in ("live_balance", "cash", "opening_balance"):
            if available.get(key) is not None:
                return float(available[key])
        return None

    def orders(self):
        return self.client.orders() if self.client else []

    def positions(self):
        return self.client.positions() if self.client else {"net": [], "day": []}

    def cancel(self, order_id):
        if not self.client:
            return None
        return self.client.cancel_order(variety=self.client.VARIETY_REGULAR, order_id=order_id)

    def exit_all_intraday(self):
        if not self.client:
            return []
        positions = self.client.positions().get("day", [])
        results=[]
        for p in positions:
            qty=int(p.get("quantity", 0))
            if qty == 0 or p.get("exchange") != "NSE":
                continue
            side=self.client.TRANSACTION_TYPE_SELL if qty > 0 else self.client.TRANSACTION_TYPE_BUY
            results.append(self.client.place_order(
                variety=self.client.VARIETY_REGULAR,
                exchange=p["exchange"],
                tradingsymbol=p["tradingsymbol"],
                transaction_type=side,
                quantity=abs(qty),
                product=p.get("product", "MIS"),
                order_type=self.client.ORDER_TYPE_MARKET,
                validity=self.client.VALIDITY_DAY,
            ))
        return results
