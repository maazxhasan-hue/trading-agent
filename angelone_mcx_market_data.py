"""Angel One SmartAPI MCX market-data feed.

Read-only/paper market data uses the authorised Angel One SmartAPI session.
No order is placed by this feed. Live execution remains controlled by the
shared fail-closed Angel One adapter and runtime gates.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from angelone_adapter import AngelOneExecution


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
    lot_size: int = 1


class AngelOneMCXFeed:
    provider = "angelone"

    def __init__(self):
        self.broker = AngelOneExecution()
        self.exchange = "MCX"
        self._instruments = {}
        self._loaded_at = 0.0
        self._history_cache = {}
        self._last_history_request = 0.0

    @property
    def is_free_data(self):
        return False

    @property
    def is_live_authorized_data(self):
        return True

    @property
    def data_label(self):
        return "angelone-authorized"

    def freshness_seconds(self, market):
        ts = getattr(market, "quote_timestamp", None)
        if ts is None:
            return float("inf")
        age = time.time() - float(ts)
        return float("inf") if age < 0 else age

    def _load_instruments(self):
        if self._instruments and time.time() - self._loaded_at < 3600:
            return
        rows = self.broker.instruments("MCX")
        allowed = {
            x.strip().upper()
            for x in os.getenv(
                "MCX_SYMBOL_FAMILIES",
                "GOLD,GOLDM,SILVER,SILVERM,CRUDEOIL,CRUDEOILM,NATURALGAS,NATURALGASM,COPPER,ZINC",
            ).split(",")
            if x.strip()
        }
        selected = {}
        for row in rows:
            symbol = str(row.get("tradingsymbol") or "").upper()
            kind = str(row.get("instrument_type") or "").upper()
            if not row.get("instrument_token") or kind not in {"FUTCOM", "FUTIDX", "FUT"}:
                continue
            if allowed and not any(symbol.startswith(name) for name in allowed):
                continue
            selected[symbol] = row
        self._instruments = selected
        self._loaded_at = time.time()
        if not self._instruments:
            raise RuntimeError("Angel One returned no supported MCX futures contracts.")

    @staticmethod
    def _timestamp(row):
        raw = (
            row.get("exchangeFeedTime")
            or row.get("exchangeTradeTime")
            or row.get("exchTradeTime")
            or row.get("lastTradeTime")
        )
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            value = float(raw)
            return value / 1000.0 if value > 10_000_000_000 else value
        text = str(raw).strip()
        for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                return datetime.strptime(text, fmt).timestamp()
            except ValueError:
                pass
        return None

    @staticmethod
    def _expiry_key(row):
        raw = str(row.get("expiry") or "")
        for fmt in ("%d%b%Y", "%d%b%y", "%Y-%m-%d", "%d-%b-%Y"):
            try:
                return datetime.strptime(raw.upper(), fmt).date()
            except ValueError:
                pass
        return datetime.max.date()

    def _symbols(self):
        self._load_instruments()
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        rows = [
            r for r in self._instruments.values()
            if self._expiry_key(r) >= today
        ]
        rows.sort(key=lambda r: (self._expiry_key(r), str(r.get("tradingsymbol", ""))))
        return rows

    def fetch(self, limit=100):
        rows = self._symbols()[:max(1, min(int(limit), 1000))]
        out = []
        # Keep the same conservative batching/rate limit used by the NSE feed.
        for start in range(0, len(rows), 50):
            chunk = rows[start:start + 50]
            tokens = [str(r["instrument_token"]) for r in chunk]
            quotes = self.broker.quote(tokens, exchange="MCX")
            for r in chunk:
                token = str(r["instrument_token"])
                q = quotes.get(token)
                if not q:
                    continue
                price = float(
                    q.get("ltp")
                    or q.get("lastTradedPrice")
                    or q.get("last_price")
                    or 0
                )
                if price <= 0:
                    continue
                buy = float(q.get("totalBuyQuantity") or 0)
                sell = float(q.get("totalSellQuantity") or 0)
                volume = float(
                    q.get("tradeVolume")
                    or q.get("volume")
                    or q.get("tradedVolume")
                    or 0
                )
                out.append(MCXMarket(
                    market_id=token,
                    question=f"{r.get('name') or r['tradingsymbol']} direction over next horizon",
                    tradingsymbol=r["tradingsymbol"],
                    instrument_token=int(token),
                    last_price=price,
                    volume=volume,
                    liquidity=buy + sell,
                    exchange="MCX",
                    quote_timestamp=self._timestamp(q),
                    lot_size=max(1, int(r.get("lot_size") or 1)),
                ))
            if start + 50 < len(rows):
                time.sleep(float(os.getenv("ANGELONE_QUOTE_INTERVAL_SECONDS", "1.05")))
        out.sort(key=lambda x: (x.volume, x.liquidity), reverse=True)
        return out

    @staticmethod
    def _interval(value):
        return {
            "1m": "ONE_MINUTE",
            "1minute": "ONE_MINUTE",
            "3m": "THREE_MINUTE",
            "5m": "FIVE_MINUTE",
            "5minute": "FIVE_MINUTE",
            "10m": "TEN_MINUTE",
            "15m": "FIFTEEN_MINUTE",
            "30m": "THIRTY_MINUTE",
            "1h": "ONE_HOUR",
            "1d": "ONE_DAY",
        }.get(str(value).lower(), "FIVE_MINUTE")

    def history(self, market, days=2, interval=None):
        interval = interval or os.getenv("MARKET_INTERVAL", "5m")
        key = (market.market_id, int(days), str(interval))
        cached = self._history_cache.get(key)
        cache_ttl = max(0.0, float(os.getenv("ANGELONE_HISTORY_CACHE_TTL_SECONDS", "240")))
        if cached is not None:
            cached_at, cached_rows = cached
            if time.time() - cached_at < cache_ttl:
                return cached_rows
        end = datetime.now(ZoneInfo("Asia/Kolkata"))
        start = end - timedelta(days=max(2, int(days)))
        min_interval = max(0.0, float(os.getenv("ANGELONE_HISTORY_REQUEST_INTERVAL_SECONDS", "0.35")))
        wait = min_interval - (time.time() - self._last_history_request)
        if wait > 0:
            time.sleep(wait)
        rows = self.broker.historical(
            market.instrument_token,
            start.strftime("%Y-%m-%d %H:%M"),
            end.strftime("%Y-%m-%d %H:%M"),
            self._interval(interval),
            exchange="MCX",
        )
        self._last_history_request = time.time()
        self._history_cache[key] = (self._last_history_request, rows)
        return rows

    def current_price(self, market_id):
        self._load_instruments()
        row = next(
            (r for r in self._instruments.values()
             if str(r.get("instrument_token")) == str(market_id)),
            None,
        )
        if not row:
            return None
        data = self.broker.ltp("MCX", row["tradingsymbol"], row["instrument_token"])
        return float(data["ltp"]) if data.get("ltp") else None

    def prefetch_history(self, markets, days=2, interval=None):
        limit = int(os.getenv("ANGELONE_HISTORY_PREFETCH_LIMIT", "10"))
        cache = {}
        for market in markets[:max(0, limit)]:
            try:
                cache[market.market_id] = self.history(market, days, interval)
            except Exception as exc:
                print("[angelone mcx history recovered]", market.tradingsymbol, repr(exc))
        # history() owns cache timestamps and rate limiting; do not insert
        # raw rows here or they would bypass the TTL on the next cycle.
        return cache
