"""Angel One SmartAPI execution adapter for the NSE engine.

Credentials are read only from environment variables. Live order placement is
fail-closed behind the existing cloud/arm gates. The adapter normalizes Angel
One responses into the small interface used by the NSE trading engine.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import pyotp
except ImportError:
    pyotp = None

try:
    from SmartApi import SmartConnect
except ImportError:
    SmartConnect = None


class AngelOneLocked(RuntimeError):
    pass


@dataclass
class OrderRequest:
    tradingsymbol: str
    symboltoken: str
    exchange: str
    transaction_type: str
    quantity: int
    price: float
    product: str = "INTRADAY"
    tag: str | None = None


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class AngelOneExecution:
    """SmartAPI client with paper/read-only/live separation."""

    def __init__(self):
        backend = os.getenv("TRADING_BACKEND", "angelone_nse").lower()
        self.enabled = (
            backend == "angelone_nse"
            and os.getenv("LIVE_TRADING", "false").lower() == "true"
        )
        self.readonly = (
            backend == "angelone_nse"
            and os.getenv("ANGELONE_READONLY", "false").lower() == "true"
        )
        self.armed = os.getenv("LIVE_TRADING_ARM") == "I_UNDERSTAND_LIVE_TRADING"
        self.cloud_runtime = os.getenv("CLOUD_RUNTIME", "false").lower() == "true"
        self.live_runtime_approved = (
            os.getenv("LIVE_RUNTIME_APPROVED", "false").lower() == "true"
        )
        self.api_key = os.getenv("ANGELONE_API_KEY", "")
        self.client_code = os.getenv("ANGELONE_CLIENT_CODE", "")
        self.pin = os.getenv("ANGELONE_PIN", "")
        self.totp_secret = os.getenv("ANGELONE_TOTP_SECRET", "")
        self.public_ip = os.getenv("ANGELONE_CLIENT_PUBLIC_IP", "")
        self.local_ip = os.getenv("ANGELONE_CLIENT_LOCAL_IP", "127.0.0.1")
        self.client = None
        self._session_day = None
        if self.enabled or self.readonly:
            self._connect()

    def _validate_credentials(self):
        missing = [
            name for name, value in (
                ("ANGELONE_API_KEY", self.api_key),
                ("ANGELONE_CLIENT_CODE", self.client_code),
                ("ANGELONE_PIN", self.pin),
                ("ANGELONE_TOTP_SECRET", self.totp_secret),
                ("ANGELONE_CLIENT_PUBLIC_IP", self.public_ip),
            ) if not value
        ]
        if missing:
            raise AngelOneLocked("Missing Angel One runtime settings: " + ", ".join(missing))
        if SmartConnect is None:
            raise AngelOneLocked("Install smartapi-python before enabling Angel One access.")
        if pyotp is None:
            raise AngelOneLocked("Install pyotp before enabling Angel One access.")

    def _connect(self):
        self._validate_credentials()
        now_day = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        self.client = SmartConnect(api_key=self.api_key)
        # The current SmartAPI Python SDK has defaults for these headers; override
        # them explicitly so the broker sees the registered Azure static public IP.
        self.client.clientPublicIP = self.public_ip
        self.client.clientLocalIP = self.local_ip
        totp = pyotp.TOTP(self.totp_secret).now()
        result = self.client.generateSession(self.client_code, self.pin, totp)
        if not result or not result.get("status"):
            message = (result or {}).get("message", "Angel One login failed")
            raise AngelOneLocked(str(message))
        self._session_day = now_day

    def _ensure_session(self):
        if self.client is None:
            raise AngelOneLocked("Angel One session is not connected.")
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        if self._session_day != today:
            self._connect()

    def status(self):
        return {
            "broker": "angelone",
            "backend": "angelone_nse",
            "live_enabled": self.enabled,
            "readonly": self.readonly,
            "armed": self.armed,
            "cloud_runtime": self.cloud_runtime,
            "live_runtime_approved": self.live_runtime_approved,
            "registered_public_ip": self.public_ip,
            "connected": self.client is not None,
        }

    def instruments(self, exchange="NSE"):
        # SmartAPI exposes the master instrument dump as a public JSON file.
        import requests
        url = os.getenv(
            "ANGELONE_INSTRUMENT_MASTER_URL",
            "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json",
        )
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        rows = response.json()
        return [
            {
                "tradingsymbol": row.get("symbol"),
                "symboltoken": row.get("token"),
                "instrument_token": row.get("token"),
                "exchange": exchange,
                "segment": "NSE" if row.get("exch_seg") == "NSE" else row.get("exch_seg"),
                "instrument_type": row.get("instrumenttype"),
                "lot_size": int(_num(row.get("lotsize"), 1) or 1),
                "name": row.get("name"),
            }
            for row in rows
            if row.get("exch_seg") == "NSE" and row.get("symbol")
        ]

    def quote(self, tokens):
        self._ensure_session()
        token_list = [str(x) for x in tokens]
        result = self.client.getMarketData("FULL", {"NSE": token_list})
        if not result or not result.get("status"):
            raise AngelOneLocked(str((result or {}).get("message", "quote failed")))
        data = result.get("data") or {}
        fetched = data.get("fetched", []) if isinstance(data, dict) else []
        out = {}
        for row in fetched:
            token = str(row.get("symbolToken") or row.get("symboltoken") or "")
            if not token:
                continue
            out[token] = row
        return out

    def ltp(self, exchange, tradingsymbol, symboltoken):
        self._ensure_session()
        result = self.client.ltpData(exchange, tradingsymbol, str(symboltoken))
        if not result or not result.get("status"):
            raise AngelOneLocked(str((result or {}).get("message", "LTP failed")))
        return result.get("data") or {}

    def historical(self, symboltoken, from_date, to_date, interval="FIVE_MINUTE"):
        self._ensure_session()
        result = self.client.getCandleData({
            "exchange": "NSE",
            "symboltoken": str(symboltoken),
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date,
        })
        if not result or not result.get("status"):
            raise AngelOneLocked(str((result or {}).get("message", "historical data failed")))
        rows = []
        for candle in result.get("data") or []:
            if len(candle) < 6:
                continue
            rows.append({
                "date": candle[0],
                "open": _num(candle[1]),
                "high": _num(candle[2]),
                "low": _num(candle[3]),
                "close": _num(candle[4]),
                "volume": _num(candle[5]),
            })
        return rows

    def funds_available(self, exchange="NSE"):
        self._ensure_session()
        result = self.client.rmsLimit()
        if not result or not result.get("status"):
            return None
        data = result.get("data") or {}
        for key in ("availablecash", "availableCash", "net", "netAvailableMargin", "cash"):
            if data.get(key) is not None:
                return _num(data[key], None)
        return None

    def positions(self):
        self._ensure_session()
        result = self.client.position()
        rows = (result or {}).get("data") or []
        normalized = []
        for row in rows:
            qty = int(_num(row.get("netqty", row.get("quantity", 0)), 0))
            if not qty:
                continue
            normalized.append({
                "tradingsymbol": row.get("tradingsymbol"),
                "exchange": row.get("exchange"),
                "quantity": qty,
                "product": row.get("producttype", "INTRADAY"),
                "average_price": _num(row.get("buyavgprice") or row.get("sellavgprice")),
            })
        return {"day": normalized, "net": normalized}

    @staticmethod
    def _normalize_order(row):
        return {
            "order_id": str(row.get("orderid") or row.get("order_id") or ""),
            "status": str(row.get("status") or row.get("orderstatus") or "").upper(),
            "quantity": int(_num(row.get("quantity"), 0)),
            "filled_quantity": int(_num(row.get("filledshares"), 0)),
            "average_price": _num(row.get("averageprice") or row.get("price")),
            "tradingsymbol": row.get("tradingsymbol"),
            "transaction_type": row.get("transactiontype"),
            "tag": row.get("ordertag", ""),
            "text": row.get("text", ""),
            "symboltoken": str(row.get("symboltoken") or ""),
            "exchange": row.get("exchange"),
        }

    def orders(self):
        self._ensure_session()
        result = self.client.orderBook()
        return [self._normalize_order(x) for x in ((result or {}).get("data") or [])]

    def place_limit(self, request: OrderRequest):
        if not self.enabled:
            raise AngelOneLocked("Live execution is disabled; use paper mode.")
        if not self.armed:
            raise AngelOneLocked("LIVE_TRADING=true requires LIVE_TRADING_ARM.")
        if not self.cloud_runtime or not self.live_runtime_approved:
            raise AngelOneLocked("Live Angel One execution requires approved cloud runtime.")
        if request.quantity <= 0 or request.price <= 0:
            raise ValueError("Invalid quantity/price")
        if request.transaction_type not in {"BUY", "SELL"}:
            raise ValueError("Invalid transaction type")
        self._ensure_session()
        payload = {
            "variety": "NORMAL",
            "tradingsymbol": request.tradingsymbol,
            "symboltoken": str(request.symboltoken),
            "transactiontype": request.transaction_type,
            "exchange": request.exchange,
            "ordertype": "LIMIT",
            "producttype": request.product,
            "duration": "DAY",
            "price": str(request.price),
            "squareoff": "0",
            "stoploss": "0",
            "quantity": str(request.quantity),
            "ordertag": request.tag[:19] if request.tag else None,
        }
        order_id = self.client.placeOrder(payload)
        if not order_id:
            raise AngelOneLocked("Angel One returned no order ID.")
        return str(order_id)

    def cancel(self, order_id):
        if not self.enabled:
            raise AngelOneLocked("Live execution is disabled.")
        self._ensure_session()
        result = self.client.cancelOrder(str(order_id), "NORMAL")
        return result

    def exit_all_intraday(self, exchange="NSE"):
        if not self.enabled:
            return []
        self._ensure_session()
        results = []
        for position in self.positions().get("day", []):
            qty = int(position.get("quantity", 0))
            if qty == 0 or position.get("exchange") != exchange:
                continue
            side = "SELL" if qty > 0 else "BUY"
            token = position.get("symboltoken")
            if not token:
                # The position endpoint may omit the token; fail closed rather
                # than guessing a symbol token for a real exit.
                raise AngelOneLocked(
                    f"Cannot safely square off {position.get('tradingsymbol')}: symbol token missing."
                )
            payload = {
                "variety": "NORMAL",
                "tradingsymbol": position["tradingsymbol"],
                "symboltoken": str(token),
                "transactiontype": side,
                "exchange": exchange,
                "ordertype": "MARKET",
                "producttype": position.get("product", "INTRADAY"),
                "duration": "DAY",
                "price": "0",
                "squareoff": "0",
                "stoploss": "0",
                "quantity": str(abs(qty)),
            }
            results.append(self.client.placeOrder(payload))
        return results
