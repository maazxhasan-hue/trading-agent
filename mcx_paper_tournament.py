"""Paper-only bridge between MCX market snapshots, isolated GEN books and ledger.

The caller supplies one independently produced signal per generation. This module
never fabricates signals, calls broker APIs, or enables live execution. Missing or
stale prices cannot be used to fabricate retirement fills.
"""
from __future__ import annotations

from typing import Callable, Iterable
from mcx_paper_portfolios import MCXPaperPortfolioBook
from mcx_tournament import TournamentLedger


class MCXPaperTournamentBridge:
    def __init__(
        self,
        ledger: TournamentLedger,
        portfolios: MCXPaperPortfolioBook,
        population_size: int = 5,
        max_quote_age_seconds: float = 10.0,
        manage_replacements: bool = True,
    ):
        self.ledger = ledger
        self.portfolios = portfolios
        self.population_size = max(1, int(population_size))
        self.max_quote_age_seconds = max(0.0, float(max_quote_age_seconds))
        self.manage_replacements = bool(manage_replacements)
        self._ensure_population()

    def active_generations(self):
        return sorted(
            int(key)
            for key, record in self.ledger.state.get("generations", {}).items()
            if record.get("stage") == "GEN_TOURNAMENT"
            and record.get("status") == "ACTIVE"
        )

    def _ensure_population(self):
        records = self.ledger.state.setdefault("generations", {})
        active = self.active_generations()
        next_generation = max((int(k) for k in records), default=0) + 1
        while len(active) < self.population_size:
            self.ledger.ensure_generation(next_generation)
            self.portfolios.ensure_generation(next_generation)
            active.append(next_generation)
            next_generation += 1
        for generation in active:
            self.portfolios.ensure_generation(generation)

    @staticmethod
    def _market_dict(market):
        return {
            "market_id": str(market.market_id),
            "tradingsymbol": str(getattr(market, "tradingsymbol", market.market_id)),
            "last_price": float(market.last_price),
            "lot_size": max(1, int(getattr(market, "lot_size", 1) or 1)),
        }

    def run_cycle(
        self,
        markets: Iterable,
        signal_provider: Callable[[int, object], int | dict | None],
        quote_age_seconds: Callable[[object], float] | None = None,
    ) -> dict:
        """Process one quote cycle; signal_provider must isolate strategy per GEN.

        Markets should be the fresh MCX snapshot objects from the configured feed.
        A stale quote is skipped for all candidates. Provider exceptions are
        recorded as candidate errors and fail closed for that market/generation.
        """
        market_list = list(markets)
        prices = {str(m.market_id): float(m.last_price) for m in market_list
                  if float(getattr(m, "last_price", 0) or 0) > 0}
        results = []
        for generation in self.active_generations():
            opened = 0
            closed = []
            skipped = 0
            errors = []
            for market in market_list:
                market_id = str(market.market_id)
                price = float(getattr(market, "last_price", 0) or 0)
                if price <= 0:
                    skipped += 1
                    continue
                if quote_age_seconds is not None:
                    try:
                        age = float(quote_age_seconds(market))
                    except Exception as exc:
                        skipped += 1
                        errors.append({"market_id": market_id, "error": "quote_age_unavailable"})
                        continue
                    if age < 0 or age > self.max_quote_age_seconds:
                        skipped += 1
                        continue
                try:
                    signal = signal_provider(generation, market)
                    if signal is None:
                        signal = 0
                    outcome = self.portfolios.process_snapshot(
                        generation, self._market_dict(market), signal
                    )
                    opened += int(bool(outcome.get("opened")))
                    closed.extend(outcome.get("closed_trades", []))
                except Exception as exc:
                    skipped += 1
                    errors.append({"market_id": market_id, "error": type(exc).__name__})
            for trade in closed:
                card = self.ledger.record_trade(
                    generation,
                    float(trade["gross_pnl"]),
                    fees=float(trade["fees"]),
                    slippage=float(trade["slippage"]),
                    timestamp=trade["closed_at"],
                )
                if card.get("status") == "RETIRED":
                    # Close other virtual positions only using this cycle's known
                    # prices. Missing prices remain open and are explicitly reported.
                    more = self.portfolios.close_generation(
                        generation, prices, reason="generation_retired"
                    )
                    # The first net loss retires this GEN. Remaining positions are
                    # closed in the paper book for accounting, but cannot add
                    # post-retirement trades to the tournament ledger.
                    break
            results.append({
                "generation": generation,
                "opened": opened,
                "closed": len(closed),
                "skipped": skipped,
                "errors": errors,
                "portfolio": self.portfolios.snapshot(generation, prices),
                "status": self.ledger.state["generations"][str(generation)]["status"],
            })
        if self.manage_replacements:
            self._ensure_population()
        return {
            "results": results,
            "active_generations": self.active_generations(),
            "live_orders_enabled": False,
            "broker_orders_submitted": 0,
        }
