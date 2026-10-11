"""Angel One SmartAPI execution adapter for NSE and MCX.

Credentials are read only from environment variables. Live order placement is
fail-closed behind the existing cloud/arm gates. The adapter normalizes Angel
One responses into the small interface used by the NSE trading engine.
"""
from __future__ import annotations

import os
import time
import json
import logging
import threading
from urllib.parse import urljoin

import requests

from angelone_auth import AngelOneAuthManager, AuthResponse, AuthSettings, AuthBlocked
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


_AUTH_MANAGERS = {}
_AUTH_MANAGERS_LOCK = threading.Lock()

def _manager_for_environment(api_key, client_code, pin, totp_secret, public_ip, local_ip):
    state_path = os.getenv("ANGELONE_AUTH_STATE_PATH", "/var/lib/trading-agent/angelone-auth.json")
    with _AUTH_MANAGERS_LOCK:
        if state_path in _AUTH_MANAGERS:
            return _AUTH_MANAGERS[state_path]
        if SmartConnect is None or pyotp is None:
            raise AngelOneLocked("Angel One client dependencies are unavailable.")

        def make_client(tokens=None):
            # SmartAPI's bundled logger emits full headers and request bodies on
            # errors. Suppress it before the client can make any API call.
            logging.getLogger("logzero_default").disabled = True
            logging.getLogger("SmartApi.smartConnect").disabled = True
            client = SmartConnect(api_key=api_key)
            client.debug = False
            client.clientPublicIP = public_ip
            client.clientLocalIP = local_ip
            if tokens:
                client.setAccessToken(tokens["jwtToken"])
                client.setRefreshToken(tokens["refreshToken"])
                client.setFeedToken(tokens["feedToken"])
                client.setUserId(client_code)
            return client

        def login_transport():
            client = make_client()
            headers = client.requestHeaders()
            body = {"clientcode": client_code, "password": pin, "totp": pyotp.TOTP(totp_secret).now()}
            try:
                response = requests.post(
                    urljoin(client.root.rstrip("/") + "/", client._routes["api.login"].lstrip("/")),
                    headers=headers, json=body, timeout=client.timeout,
                )
                try:
                    data = response.json()
                except ValueError:
                    data = {"message": "non_json_response"}
                return AuthResponse(response.status_code, dict(response.headers), data if isinstance(data, dict) else {})
            except requests.RequestException:
                raise OSError("Angel One login transport failed") from None

        def refresh_transport(tokens):
            client = make_client(tokens)
            headers = client.requestHeaders()
            headers["Authorization"] = "Bearer " + tokens["jwtToken"]
            try:
                response = requests.post(
                    urljoin(client.root.rstrip("/") + "/", client._routes["api.token"].lstrip("/")),
                    headers=headers, json={"refreshToken": tokens["refreshToken"]}, timeout=client.timeout,
                )
                try:
                    data = response.json()
                except ValueError:
                    data = {"message": "non_json_response"}
                return AuthResponse(response.status_code, dict(response.headers), data if isinstance(data, dict) else {})
            except requests.RequestException:
                raise OSError("Angel One session refresh transport failed") from None

        settings = AuthSettings(
            state_path=__import__("pathlib").Path(state_path),
            cooldown_seconds=float(os.getenv("ANGELONE_AUTH_COOLDOWN_SECONDS", "900")),
            min_interval_seconds=float(os.getenv("ANGELONE_AUTH_MIN_INTERVAL_SECONDS", "1")),
            max_attempts=int(os.getenv("ANGELONE_AUTH_MAX_ATTEMPTS", "3")),
        )
        manager = AngelOneAuthManager(settings=settings, transport=login_transport, client_factory=make_client, refresh_transport=refresh_transport)
        _AUTH_MANAGERS[state_path] = manager
        return manager


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
        self.backend = backend
        self.enabled = (
            backend in {"angelone_nse", "angelone_mcx"}
            and os.getenv("LIVE_TRADING", "false").lower() == "true"
        )
        self.readonly = (
            backend in {"angelone_nse", "angelone_mcx"}
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
        self.auth_manager = None
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
        try:
            self.auth_manager = _manager_for_environment(
                self.api_key, self.client_code, self.pin, self.totp_secret,
                self.public_ip, self.local_ip,
            )
            self.client = self.auth_manager.get_client()
            self._session_day = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        except AuthBlocked as exc:
            self.client = None
            raise AngelOneLocked(str(exc)) from None
        except Exception:
            self.client = None
            raise AngelOneLocked("Angel One authentication is unavailable.") from None

    def _ensure_session(self):
        if self.auth_manager is None:
            raise AngelOneLocked("Angel One session is not connected.")
        try:
            self.client = self.auth_manager.get_client()
        except AuthBlocked as exc:
            raise AngelOneLocked(str(exc)) from None

    def _api_call(self, method, *args):
        try:
            return getattr(self.client, method)(*args)
        except Exception as exc:
            message = str(exc).lower()
            code = getattr(exc, "code", None)
            recognized_expiry = code == 403 and any(term in message for term in ("tokenexception", "token expired", "invalid token"))
            if not recognized_expiry or self.auth_manager is None:
                raise AngelOneLocked("SmartAPI request failed.") from None
            rejected_token = getattr(self.client, "access_token", None)
            self.client = self.auth_manager.handle_expired_session(rejected_token=rejected_token)
            try:
                return getattr(self.client, method)(*args)
            except Exception:
                raise AngelOneLocked("SmartAPI request failed after session refresh.") from None

    def status(self):
        return {
            "broker": "angelone",
            "backend": self.backend,
            "live_enabled": self.enabled,
            "readonly": self.readonly,
            "armed": self.armed,
            "cloud_runtime": self.cloud_runtime,
            "live_runtime_approved": self.live_runtime_approved,
            "registered_public_ip": self.public_ip,
            "connected": self.client is not None,
            "auth_status": self.auth_manager.status()["status"] if self.auth_manager else "AUTH_REQUIRED",
            "cooldown_remaining_seconds": self.auth_manager.status()["cooldown_remaining_seconds"] if self.auth_manager else 0,
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
                "segment": row.get("exch_seg"),
                "instrument_type": row.get("instrumenttype"),
                "lot_size": int(_num(row.get("lotsize"), 1) or 1),
                "expiry": row.get("expiry"),
                "name": row.get("name"),
            }
            for row in rows
            if row.get("exch_seg") == exchange and row.get("symbol")
        ]

    def quote(self, tokens, exchange="NSE"):
        """Fetch market quotes, using LTP mode for MCX when configured.

        Angel One's MCX FULL quote endpoint can be unavailable on some
        authorised cloud IPs while the LTP market-data mode remains healthy.
        MCX therefore defaults to LTP mode; NSE keeps FULL as its default.
        """
        self._ensure_session()
        out = {}
        mode = os.getenv("ANGELONE_MARKET_DATA_MODE", "").strip().upper()
        if not mode:
            mode = "LTP" if exchange.upper() == "MCX" else "FULL"
        if mode not in {"FULL", "LTP"}:
            raise AngelOneLocked("ANGELONE_MARKET_DATA_MODE must be FULL or LTP.")
        for raw_token in tokens:
            token = str(raw_token)
            try:
                result = self._api_call("getMarketData", mode, {exchange: [token]})
                if not result or not result.get("status"):
                    raise AngelOneLocked(
                        "quote failed"
                    )
                data = result.get("data") or {}
                fetched = data.get("fetched", []) if isinstance(data, dict) else []
                for row in fetched:
                    row_token = str(
                        row.get("symbolToken")
                        or row.get("symboltoken")
                        or token
                    )
                    out[row_token] = row
            except Exception as exc:
                # A single malformed/empty SmartAPI response must not terminate
                # an entire MCX scan. The next cycle retries the token.
                print(
                    "[angelone quote recovered]",
                    exchange,
                    token,
                    type(exc).__name__,
                    "request_failed",
                )
            finally:
                # SmartAPI currently documents one token/request and a 10 req/sec
                # market-data limit. Stay comfortably below that limit.
                time.sleep(float(os.getenv("ANGELONE_QUOTE_INTERVAL_SECONDS", "0.12")))
        return out

    def ltp(self, exchange, tradingsymbol, symboltoken):
        self._ensure_session()
        result = self._api_call("ltpData", exchange, tradingsymbol, str(symboltoken))
        if not result or not result.get("status"):
            raise AngelOneLocked("Angel One LTP request failed.")
        return result.get("data") or {}

    def historical(self, symboltoken, from_date, to_date, interval="FIVE_MINUTE", exchange="NSE"):
        self._ensure_session()
        result = self._api_call("getCandleData", {
            "exchange": exchange,
            "symboltoken": str(symboltoken),
            "interval": interval,
            "fromdate": from_date,
            "todate": to_date,
        })
        if not result or not result.get("status"):
            raise AngelOneLocked("Angel One historical data request failed.")
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
        result = self._api_call("rmsLimit", )
        if not result or not result.get("status"):
            return None
        data = result.get("data") or {}
        for key in ("availablecash", "availableCash", "net", "netAvailableMargin", "cash"):
            if data.get(key) is not None:
                return _num(data[key], None)
        return None

    def positions(self):
        self._ensure_session()
        result = self._api_call("position", )
        rows = (result or {}).get("data") or []
        normalized = []
        for row in rows:
            qty = int(_num(row.get("netqty", row.get("quantity", 0)), 0))
            if not qty:
                continue
            normalized.append({
                "tradingsymbol": row.get("tradingsymbol"),
                "symboltoken": str(row.get("symboltoken") or ""),
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
        result = self._api_call("orderBook", )
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
        if self.backend == "angelone_mcx" and request.exchange != "MCX":
            raise AngelOneLocked("Angel One MCX backend refuses non-MCX orders.")
        if self.backend == "angelone_mcx" and request.product not in {"CARRYFORWARD", "NRML"}:
            raise AngelOneLocked("Angel One MCX futures require CARRYFORWARD/NRML product.")
        if (
            self.backend == "angelone_mcx"
            and os.getenv("MCX_LIVE_EXIT_PROTECTION_VERIFIED", "false").strip().lower() != "true"
        ):
            raise AngelOneLocked(
                "MCX live order blocked: protective exit handling has not been implemented "
                "and independently verified. Keep paper mode enabled."
            )
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
        order_id = self._api_call("placeOrder", payload)
        if not order_id:
            raise AngelOneLocked("Angel One returned no order ID.")
        return str(order_id)

    def cancel(self, order_id):
        if not self.enabled:
            raise AngelOneLocked("Live execution is disabled.")
        self._ensure_session()
        result = self._api_call("cancelOrder", str(order_id), "NORMAL")
        return result

    def exit_all_intraday(self, exchange=None):
        exchange = exchange or ("MCX" if self.backend == "angelone_mcx" else "NSE")
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
            results.append(self._api_call("placeOrder", payload))
        return results
