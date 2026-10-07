"""MCX trading entrypoint.

The core multi-agent engine is shared with the hardened NSE implementation;
the runtime feed/session/exchange are selected through the MCX environment.
"""
from nse_agent import NSETradingCompany as MCXTradingCompany

__all__ = ["MCXTradingCompany"]

if __name__ == "__main__":
    MCXTradingCompany().run()
