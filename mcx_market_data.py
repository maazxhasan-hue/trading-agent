"""MCX market-data layer.

Live mode: Zerodha Kite Connect MCX instruments/quotes/historical candles.
Paper mode: optional Yahoo global-futures proxies for strategy validation only.
Yahoo is never treated as an exchange-authorised live feed.
"""
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from zerodha_adapter import ZerodhaExecution


@dataclass
class MCXMarket:
    market_id: str
    question: str
    tradingsymbol: str
    instrument_token: int
    last_price: float
    volume: float
    liquidity: float
    exchange: str = "MCX"
    quote_timestamp: float | None = None


class MCXPublicFeed:
    YAHOO = {
        "GOLD": "GC=F",
        "SILVER": "SI=F",
        "CRUDEOIL": "CL=F",
        "NATURALGAS": "NG=F",
        "COPPER": "HG=F",
    }

    def __init__(self):
        self.provider = os.getenv("MCX_MARKET_DATA_PROVIDER", "yahoo").lower()
        if self.provider not in {"yahoo", "zerodha"}:
            raise ValueError("MCX_MARKET_DATA_PROVIDER must be 'yahoo' or 'zerodha'.")
        self.broker = ZerodhaExecution()
        self._instruments = {}
        self._loaded_at = 0.0
        self._yf = None
        if self.provider == "zerodha":
            if not self.broker.client:
                raise RuntimeError("MCX Zerodha data requires KITE_READONLY=true or live runtime credentials.")
            self._load_instruments()

    @property
    def is_free_data(self):
        return self.provider == "yahoo"

    @property
    def is_live_authorized_data(self):
        return self.provider == "zerodha"

    @property
    def data_label(self):
        return "zerodha-authorized" if self.is_live_authorized_data else "free-research-proxy"

    def freshness_seconds(self, market):
        if self.provider != "zerodha":
            return float("inf")
        ts = market.quote_timestamp
        return float("inf") if ts is None else max(0.0, time.time() - float(ts))

    @staticmethod
    def _timestamp(q):
        for key in ("timestamp", "last_trade_time", "exchange_timestamp"):
            v = q.get(key) if isinstance(q, dict) else None
            if v is None:
                continue
            if isinstance(v, datetime):
                return v.timestamp()
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
        return None

    def _load_instruments(self):
        rows = self.broker.instruments("MCX")
        self._instruments = {
            str(r["tradingsymbol"]): r for r in rows
            if r.get("instrument_token") and r.get("instrument_type") in {"FUT", "FUTCOM"}
        }
        self._loaded_at = time.time()

    def _ensure_instruments(self):
        if not self._instruments or time.time() - self._loaded_at > 3600:
            self._load_instruments()

    def _fetch_zerodha(self, limit):
        self._ensure_instruments()
        now = datetime.now().date()
        names = tuple(x.strip().upper() for x in os.getenv(
            "MCX_SYMBOL_FAMILIES", "GOLD,GOLDM,SILVER,SILVERM,CRUDEOIL,CRUDEOILM,NATURALGAS,NATURALGASM,COPPER,ZINC"
        ).split(",") if x.strip())
        rows = []
        for symbol, r in self._instruments.items():
            expiry = r.get("expiry")
            if expiry and expiry < now:
                continue
            name = str(r.get("name") or "").upper()
            ts = symbol.upper()
            if names and not any(n in name or ts.startswith(n) for n in names):
                continue
            rows.append(r)
        rows.sort(key=lambda r: (r.get("expiry") or now, str(r.get("tradingsymbol"))))
        rows = rows[:limit]
        keys = [f"MCX:{r['tradingsymbol']}" for r in rows]
        quotes = self.broker.quote(keys)
        out = []
        for r in rows:
            key = f"MCX:{r['tradingsymbol']}"
            q = quotes.get(key, {})
            price = float(q.get("last_price") or 0)
            if price <= 0:
                continue
            out.append(MCXMarket(
                market_id=f"MCX:{r['tradingsymbol']}",
                question=f"{r.get('name','MCX')} {r['tradingsymbol']} direction over next horizon",
                tradingsymbol=r["tradingsymbol"],
                instrument_token=int(r["instrument_token"]),
                last_price=price,
                volume=float(q.get("volume") or 0),
                liquidity=float(q.get("depth", {}).get("buy", [{}])[0].get("quantity", 0) if isinstance(q.get("depth"), dict) else 0),
                quote_timestamp=self._timestamp(q),
            ))
        return out

    def _yahoo(self):
        if self._yf is None:
            try:
                import yfinance as yf
                self._yf = yf
            except ImportError as exc:
                raise RuntimeError("yfinance is required for free MCX paper research.") from exc
        return self._yf

    def _fetch_yahoo(self, limit):
        yf = self._yahoo()
        out = []
        for name, ticker in list(self.YAHOO.items())[:limit]:
            try:
                data = yf.download(ticker, period="2d", interval="5m", progress=False, auto_adjust=False, threads=False)
                if data is None or data.empty:
                    continue
                row = data.iloc[-1]
                def val(k):
                    x = row[k]
                    try:
                        return float(x.iloc[0]) if hasattr(x, "iloc") else float(x)
                    except Exception:
                        return 0.0
                price = val("Close")
                if price <= 0:
                    continue
                out.append(MCXMarket(
                    market_id=f"MCX-PROXY:{name}",
                    question=f"{name} global futures proxy direction over next horizon",
                    tradingsymbol=name,
                    instrument_token=0,
                    last_price=price,
                    volume=val("Volume"),
                    liquidity=val("Volume"),
                    exchange="MCX",
                    quote_timestamp=None,
                ))
            except Exception as exc:
                print("[mcx yahoo recovered]", name, repr(exc))
        return out

    def fetch(self, limit=100):
        return self._fetch_zerodha(limit) if self.provider == "zerodha" else self._fetch_yahoo(limit)

    def history(self, market, days=2, interval="5m"):
        if self.provider == "zerodha":
            if not market.instrument_token:
                return []
            end = datetime.now()
            start = end - timedelta(days=days)
            kite_interval = {"1m":"minute","5m":"5minute","15m":"15minute","30m":"30minute","60m":"60minute"}.get(interval, "5minute")
            return self.broker.historical(market.instrument_token, start, end, kite_interval)
        yf = self._yahoo()
        ticker = self.YAHOO.get(market.tradingsymbol, market.tradingsymbol)
        data = yf.download(ticker, period=f"{max(2, days)}d", interval=interval, progress=False, auto_adjust=False, threads=False)
        rows = []
        if data is None or data.empty:
            return rows
        for idx, row in data.iterrows():
            def num(k):
                x = row[k]
                try:
                    return float(x.iloc[0]) if hasattr(x, "iloc") else float(x)
                except Exception:
                    return 0.0
            rows.append({"close":num("Close"),"open":num("Open"),"high":num("High"),"low":num("Low"),"volume":num("Volume")})
        return rows

    def prefetch_history(self, markets, days=2, interval="5m"):
        return {m.market_id: self.history(m, days, interval) for m in markets}
