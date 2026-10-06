"""NSE market-data layer with a zero-cost research/paper path.

Providers:
- zerodha: broker quotes + historical candles (requires paid Connect data access).
- yahoo: free Yahoo Finance research data through yfinance. It is not an
  exchange-authorised real-time feed and is therefore PAPER-ONLY.

The free path exists so the strategy/learning stack can be exercised without
buying Kite Connect market-data access. Live Zerodha order execution remains
independently gated in nse_agent.py.
"""
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from zerodha_adapter import ZerodhaExecution

try:
    import yfinance as yf
except ImportError:
    yf = None


@dataclass
class NSEMarket:
    market_id: str
    question: str
    tradingsymbol: str
    instrument_token: int
    last_price: float
    volume: float
    liquidity: float
    exchange: str = "NSE"


class NSEPublicFeed:
    def __init__(self):
        self.provider = os.getenv("NSE_MARKET_DATA_PROVIDER", "yahoo").lower()
        if self.provider not in {"yahoo", "zerodha"}:
            raise ValueError("NSE_MARKET_DATA_PROVIDER must be 'yahoo' or 'zerodha'.")
        self.broker = ZerodhaExecution()
        self._instruments = {}
        self._loaded_at = 0.0
        if self.provider == "zerodha":
            self._load_instruments()

    @property
    def is_free_data(self):
        return self.provider == "yahoo"

    @property
    def is_live_authorized_data(self):
        return self.provider == "zerodha"

    def _load_instruments(self):
        if not self.broker.client:
            return
        rows = self.broker.instruments("NSE")
        self._instruments = {
            str(r["tradingsymbol"]): r
            for r in rows
            if r.get("instrument_token")
        }
        self._loaded_at = time.time()

    def _ensure_instruments(self):
        if time.time() - self._loaded_at > 3600 or not self._instruments:
            self._load_instruments()

    def _symbols(self):
        allow = [
            x.strip().upper()
            for x in os.getenv("NSE_SYMBOLS", "").split(",")
            if x.strip()
        ]
        if not allow:
            raise RuntimeError(
                "NSE_SYMBOLS must be set for the free Yahoo provider. "
                "Example: NSE_SYMBOLS=RELIANCE,INFY,HDFCBANK,TCS"
            )
        return allow[:1000]

    @staticmethod
    def _yahoo_symbol(symbol):
        return f"{symbol}.NS"

    def _fetch_yahoo(self, symbols):
        if yf is None:
            raise RuntimeError("Install yfinance for the free market-data provider.")
        out = []
        for symbol in symbols:
            ticker = yf.Ticker(self._yahoo_symbol(symbol))
            try:
                hist = ticker.history(period="2d", interval="5m", auto_adjust=False)
            except Exception as exc:
                print("[yahoo data recovered]", symbol, repr(exc))
                continue
            if hist is None or hist.empty:
                continue
            last = hist.iloc[-1]
            try:
                price = float(last["Close"])
                volume = float(last.get("Volume", 0) or 0)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            # Yahoo data is not treated as an authorised real-time execution feed.
            liquidity = volume * price
            out.append(
                NSEMarket(
                    market_id=symbol,
                    question=symbol,
                    tradingsymbol=symbol,
                    instrument_token=0,
                    last_price=price,
                    volume=volume,
                    liquidity=liquidity,
                )
            )
        out.sort(key=lambda x: (x.volume, x.liquidity), reverse=True)
        return out

    def fetch(self, limit=500):
        if self.provider == "yahoo":
            return self._fetch_yahoo(self._symbols()[:max(1, min(int(limit), 1000))])

        self._ensure_instruments()
        if not self._instruments:
            raise RuntimeError(
                "Zerodha market data unavailable: configure "
                "KITE_API_KEY/KITE_ACCESS_TOKEN and a data-enabled Kite plan."
            )
        allow = {
            x.strip().upper()
            for x in os.getenv("NSE_SYMBOLS", "").split(",")
            if x.strip()
        }
        rows = list(self._instruments.values())
        if allow:
            rows = [r for r in rows if r["tradingsymbol"].upper() in allow]
        else:
            rows = [
                r for r in rows
                if r.get("segment") == "NSE" and r.get("instrument_type") == "EQ"
            ]
        rows = rows[:max(1, min(int(limit), 1000))]
        symbols = [f"NSE:{r['tradingsymbol']}" for r in rows]
        quotes = {}
        for i in range(0, len(symbols), 500):
            quotes.update(self.broker.quote(symbols[i:i + 500]))
        out = []
        for r in rows:
            key = f"NSE:{r['tradingsymbol']}"
            q = quotes.get(key, {})
            lp = float(q.get("last_price") or 0)
            if lp <= 0:
                continue
            depth = q.get("depth") or {}
            buy = sum(float(x.get("quantity", 0)) for x in depth.get("buy", [])[:5])
            sell = sum(float(x.get("quantity", 0)) for x in depth.get("sell", [])[:5])
            out.append(
                NSEMarket(
                    str(r["instrument_token"]),
                    r["tradingsymbol"],
                    r["tradingsymbol"],
                    int(r["instrument_token"]),
                    lp,
                    float(q.get("volume") or 0),
                    buy + sell,
                )
            )
        out.sort(key=lambda x: (x.volume, x.liquidity), reverse=True)
        return out

    def current_price(self, market_id):
        if self.provider == "yahoo":
            if yf is None:
                return None
            symbol = str(market_id).upper().replace(".NS", "")
            try:
                hist = yf.Ticker(self._yahoo_symbol(symbol)).history(
                    period="1d", interval="5m", auto_adjust=False
                )
                if hist is not None and not hist.empty:
                    return float(hist.iloc[-1]["Close"])
            except Exception:
                return None
            return None

        self._ensure_instruments()
        row = next(
            (
                r for r in self._instruments.values()
                if str(r.get("instrument_token")) == str(market_id)
            ),
            None,
        )
        if not row:
            return None
        key = f"NSE:{row['tradingsymbol']}"
        q = self.broker.quote([key]).get(key, {})
        return float(q.get("last_price")) if q.get("last_price") else None

    def history(self, market, days=30, interval=None):
        interval = interval or os.getenv("NSE_INTERVAL", "5minute")
        if self.provider == "yahoo":
            if yf is None:
                raise RuntimeError("Install yfinance for the free market-data provider.")
            symbol = market.tradingsymbol
            ticker = yf.Ticker(self._yahoo_symbol(symbol))
            period = "1mo" if int(days) <= 31 else "3mo"
            hist = ticker.history(
                period=period,
                interval=interval,
                auto_adjust=False,
            )
            if hist is None or hist.empty:
                return []
            rows = []
            for idx, row in hist.dropna(subset=["Close"]).iterrows():
                rows.append(
                    {
                        "date": idx.isoformat(),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": float(row.get("Volume", 0) or 0),
                    }
                )
            return rows

        end = datetime.now()
        start = end - timedelta(days=max(2, int(days)))
        return self.broker.historical(
            market.instrument_token,
            start.strftime("%Y-%m-%d %H:%M:%S"),
            end.strftime("%Y-%m-%d %H:%M:%S"),
            interval,
        )
