"""NSE cash-market data layer backed by Zerodha Kite Connect.

This is a real market adapter, not a mock. Paper mode only changes execution;
data is still sourced from the broker when credentials are available.
"""
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from zerodha_adapter import ZerodhaExecution


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
        self.broker = ZerodhaExecution()
        self._instruments = {}
        self._loaded_at = 0.0
        self._load_instruments()

    def _load_instruments(self):
        if not self.broker.client:
            return
        rows=self.broker.instruments("NSE")
        self._instruments={str(r["tradingsymbol"]): r for r in rows if r.get("instrument_token")}
        self._loaded_at=time.time()

    def _ensure_instruments(self):
        if time.time()-self._loaded_at > 3600 or not self._instruments:
            self._load_instruments()

    def fetch(self, limit=500):
        self._ensure_instruments()
        if not self._instruments:
            raise RuntimeError("Zerodha market data unavailable: configure KITE_API_KEY/KITE_ACCESS_TOKEN.")
        allow={x.strip().upper() for x in os.getenv("NSE_SYMBOLS", "").split(",") if x.strip()}
        rows=list(self._instruments.values())
        if allow:
            rows=[r for r in rows if r["tradingsymbol"].upper() in allow]
        else:
            # Liquid, currently tradable equities only; final ranking comes from live quote volume.
            rows=[r for r in rows if r.get("segment")=="NSE" and r.get("instrument_type")=="EQ"]
        rows=rows[:max(1, min(int(limit), 1000))]
        symbols=[f"NSE:{r['tradingsymbol']}" for r in rows]
        quotes={}
        for i in range(0,len(symbols),500):
            quotes.update(self.broker.quote(symbols[i:i+500]))
        out=[]
        for r in rows:
            key=f"NSE:{r['tradingsymbol']}"
            q=quotes.get(key,{})
            lp=float(q.get("last_price") or 0)
            if lp <= 0: continue
            depth=q.get("depth") or {}
            buy=sum(float(x.get("quantity",0)) for x in depth.get("buy",[])[:5])
            sell=sum(float(x.get("quantity",0)) for x in depth.get("sell",[])[:5])
            out.append(NSEMarket(str(r["instrument_token"]),r["tradingsymbol"],r["tradingsymbol"],int(r["instrument_token"]),lp,float(q.get("volume") or 0),buy+sell))
        out.sort(key=lambda x:(x.volume,x.liquidity), reverse=True)
        return out

    def current_price(self, market_id):
        self._ensure_instruments()
        row=next((r for r in self._instruments.values() if str(r.get("instrument_token"))==str(market_id)),None)
        if not row: return None
        q=self.broker.quote([f"NSE:{row['tradingsymbol']}"]).get(f"NSE:{row['tradingsymbol']}",{})
        return float(q.get("last_price")) if q.get("last_price") else None

    def history(self, market, days=30, interval=None):
        interval=interval or os.getenv("NSE_INTERVAL", "5minute")
        end=datetime.now()
        start=end-timedelta(days=max(2,int(days)))
        return self.broker.historical(market.instrument_token,start.strftime("%Y-%m-%d %H:%M:%S"),end.strftime("%Y-%m-%d %H:%M:%S"),interval)
