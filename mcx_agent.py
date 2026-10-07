"""Standalone MCX trading engine entrypoint.

MCX uses the hardened multi-agent strategy/risk engine, but this entrypoint
forces the MCX backend and MCX-specific configuration. Live trading remains
blocked by the existing Zerodha safety gates until explicitly authorized.
"""

import os

# Ensure the shared engine is initialized with MCX-specific defaults before
# importing it. Explicit environment values still take precedence.
os.environ.setdefault("TRADING_BACKEND", "mcx")
os.environ.setdefault("PAPER_STATE_FILE", "data/mcx_paper_state.json")
os.environ.setdefault("AGENT_LEARNING_FILE", "data/mcx_agent_learning.json")
os.environ.setdefault("MARKET_INTERVAL", "5m")
os.environ.setdefault("MCX_MIN_CONFIDENCE", "0.58")
os.environ.setdefault("MCX_MIN_SCORE", "0.60")

from nse_agent import NSETradingCompany


class MCXTradingCompany(NSETradingCompany):
    """MCX-specific trading company using the hardened strategy/risk core."""

    def __init__(self):
        os.environ["TRADING_BACKEND"] = "mcx"

        provider = os.getenv("MCX_MARKET_DATA_PROVIDER", "zerodha").lower()
        if provider not in {"zerodha", "yahoo"}:
            raise ValueError("MCX_MARKET_DATA_PROVIDER must be 'zerodha' or 'yahoo'.")

        # The inherited engine selects MCXPublicFeed whenever TRADING_BACKEND=mcx.
        super().__init__()

        if getattr(self.feed, "exchange", "MCX") != "MCX":
            raise RuntimeError("MCX engine initialized with a non-MCX feed.")

        print(
            "[mcx] engine initialized",
            "provider=" + str(getattr(self.feed, "provider", provider)),
            "data_label=" + str(getattr(self.feed, "data_label", "unknown")),
            "live=" + str(bool(self.execution.enabled)),
        )

    def cycle(self):
        """Run one MCX scan through the hardened strategy/risk lifecycle."""
        print("[mcx] cycle start")
        super().cycle()
        print("[mcx] cycle complete")


__all__ = ["MCXTradingCompany"]


if __name__ == "__main__":
    MCXTradingCompany().run()
