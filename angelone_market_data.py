"""Angel One NSE market-data provider.

Uses the official SmartAPI instrument master and Market Data API. The API
supports up to 50 tokens per market-data request, so a 1000-symbol scan is
batched and rate-limited. Historical candles are requested only for selected
symbols, not for the whole universe every cycle.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from angelone_adapter import AngelOneExecution
from nse_market_data import NSEMarket


class AngelOneNSEFeed:
    provider = "angelone"

    def __init__(self):
        self.broker = AngelOneExecution()
        self._instruments = {}
        self._loaded_at = 0.0
        self._history_cache = {}

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
        if self._instruments and time.time() - self._loaded_at < 86400:
            return
        rows = self.broker.instruments("NSE")
        self._instruments = {
            str(r["tradingsymbol"]): r
            for r in rows
            if r.get("instrument_token")
            and str(r.get("tradingsymbol", "")).endswith("-EQ")
        }
        self._loaded_at = time.time()
        if not self._instruments:
            raise RuntimeError("Angel One returned no NSE-EQ instruments.")

    def _symbols(self):
        self._load_instruments()
        allow = [
            x.strip().upper() for x in os.getenv("NSE_SYMBOLS", "").split(",")
            if x.strip()
        ]
        if allow:
            return [
                self._instruments[s] for s in allow
                if s in self._instruments
            ][:1000]
        rows = list(self._instruments.values())
        rows.sort(key=lambda r: str(r.get("tradingsymbol", "")))
        return rows[:1000]

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

    def fetch(self, limit=1000):
        rows = self._symbols()[:max(1, min(int(limit), 1000))]
        out = []
        for start in range(0, len(rows), 50):
            chunk = rows[start:start + 50]
            tokens = [str(r["instrument_token"]) for r in chunk]
            quotes = self.broker.quote(tokens)
            for r in chunk:
                token = str(r["instrument_token"])
                q = quotes.get(token)
                if not q:
                    continue
                price = float(q.get("ltp") or q.get("lastTradedPrice") or 0)
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
                out.append(NSEMarket(
                    market_id=token,
                    question=r["tradingsymbol"],
                    tradingsymbol=r["tradingsymbol"],
                    instrument_token=int(token),
                    last_price=price,
                    volume=volume,
                    liquidity=buy + sell,
                    exchange="NSE",
                    quote_timestamp=self._timestamp(q),
                ))
            # SmartAPI documents a 1 request/sec limit for market-data requests.
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
        key = (market.market_id, int(days), str(interval or os.getenv("NSE_INTERVAL", "5m")))
        cached = self._history_cache.get(key)
        if cached is not None:
            return cached
        end = datetime.now(ZoneInfo("Asia/Kolkata"))
        start = end - timedelta(days=max(2, int(days)))
        rows = self.broker.historical(
            market.instrument_token,
            start.strftime("%Y-%m-%d %H:%M"),
            end.strftime("%Y-%m-%d %H:%M"),
            self._interval(interval or os.getenv("NSE_INTERVAL", "5m")),
        )
        self._history_cache[key] = rows
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
        data = self.broker.ltp("NSE", row["tradingsymbol"], row["instrument_token"])
        return float(data["ltp"]) if data.get("ltp") else None

    def prefetch_history(self, markets, days=2, interval=None):
        # Intentionally bounded. SmartAPI historical data is rate limited; the
        # live engine deep-researches a smaller candidate set.
        limit = int(os.getenv("ANGELONE_HISTORY_PREFETCH_LIMIT", "25"))
        cache = {}
        for market in markets[:max(0, limit)]:
            try:
                cache[market.market_id] = self.history(market, days, interval)
            except Exception as exc:
                print("[angelone history recovered]", market.tradingsymbol, repr(exc))
        self._history_cache.update(
            {(m.market_id, int(days), str(interval or os.getenv("NSE_INTERVAL", "5m"))): v
             for m, v in [(m, cache.get(m.market_id)) for m in markets[:limit]]
             if v is not None}
        )
        return cache
