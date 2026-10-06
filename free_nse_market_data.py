"""Free NSE research market-data helper.

Uses yfinance for personal research/paper workflows. It is not an
exchange-authorised real-time feed and should not be used as the sole basis
for live order decisions.
"""
import os

import yfinance as yf


def symbols():
    return [s.strip().upper() for s in os.getenv("NSE_SYMBOLS", "").split(",") if s.strip()]


def history(symbol, period="1mo", interval="5m"):
    ticker = yf.Ticker(f"{symbol.upper()}.NS")
    frame = ticker.history(period=period, interval=interval, auto_adjust=False)
    return frame


def last_price(symbol):
    frame = history(symbol, period="1d", interval="5m")
    if frame.empty:
        return None
    return float(frame.iloc[-1]["Close"])
