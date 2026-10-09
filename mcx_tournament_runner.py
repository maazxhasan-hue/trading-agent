"""Guarded orchestration for MCX paper-strategy generations.

This runner coordinates independently evaluated paper candidates through the
persistent TournamentLedger. It intentionally has no broker-order API: candidate
evaluation and Angel One validation are injected callbacks, and promotion never
enables live orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Any

from mcx_tournament import TournamentLedger


@dataclass(frozen=True)
class CandidateResult:
    generation: int
    trades: tuple[dict, ...]
    rule_violation: bool = False


class TournamentRunner:
    """Coordinate paper candidate results and champion hand-off.

    The evaluator must return closed paper-trade results only. Each trade dict
    accepts pnl (gross), optional fees, slippage, timestamp, drawdown_fraction,
    and rule_violation. No candidate can submit broker orders through this class.
    """

    def __init__(self, ledger: TournamentLedger, population_size: int = 5,
                 first_generation: int = 1):
        self.ledger = ledger
        self.population_size = max(1, int(population_size))
        self.first_generation = max(1, int(first_generation))
        self._ensure_population()

    def _ensure_population(self) -> list[int]:
        generations = self.ledger.state.setdefault("generations", {})
        existing = sorted(int(key) for key in generations)
        next_generation = max(existing, default=self.first_generation - 1) + 1
        if not existing:
            next_generation = self.first_generation
        active = [
            int(key) for key, record in generations.items()
            if record.get("stage") == "GEN_TOURNAMENT"
            and record.get("status") == "ACTIVE"
        ]
        while len(active) < self.population_size:
            generation = next_generation
            self.ledger.ensure_generation(generation)
            active.append(generation)
            next_generation += 1
        return sorted(active)

    def active_generations(self) -> list[int]:
        return sorted(
            int(key) for key, record in self.ledger.state["generations"].items()
            if record.get("stage") == "GEN_TOURNAMENT"
            and record.get("status") == "ACTIVE"
        )

    def evaluate_round(self, evaluator: Callable[[int], Iterable[dict]]) -> dict:
        """Evaluate every active generation once and persist all returned trades."""
        evaluated = []
        for generation in self.active_generations():
            trade_results = list(evaluator(generation) or [])
            recorded = []
            for trade in trade_results:
                if not isinstance(trade, dict) or "pnl" not in trade:
                    raise ValueError("each paper trade must be a dict containing pnl")
                card = self.ledger.record_trade(
                    generation,
                    trade["pnl"],
                    fees=trade.get("fees", 0.0),
                    slippage=trade.get("slippage", 0.0),
                    timestamp=trade.get("timestamp"),
                    drawdown_fraction=trade.get("drawdown_fraction", 0.0),
                    rule_violation=trade.get("rule_violation", False),
                )
                recorded.append(card)
                if card["status"] == "RETIRED":
                    # One loss retires the generation. Do not accept additional
                    # trades for this generation in the same evaluation batch.
                    break
            evaluated.append({
                "generation": generation,
                "trades_recorded": len(recorded),
                "status": self.ledger.state["generations"][str(generation)]["status"],
                "latest_scorecard": recorded[-1] if recorded else self.ledger.scorecard(generation),
            })
        self._ensure_population()
        return {
            "evaluated": evaluated,
            "active_generations": self.active_generations(),
            "champion": None,
            "live_orders_enabled": False,
        }

    def select_champion_for_validation(self, now=None) -> dict | None:
        """Promote the best eligible paper generation into validation state."""
        winner = self.ledger.select_champion(now=now)
        if winner is None:
            return None
        self.ledger.begin_angelone_validation(winner["generation"])
        return {
            **winner,
            "validation_started": True,
            "live_orders_enabled": False,
            "requires_angelone_paper_validation": True,
        }

    def complete_validation(self, generation: int, evidence: dict) -> dict:
        """Apply explicit Angel One validation evidence; never enables live orders."""
        required = {
            "net_pnl", "trades", "duration_seconds", "max_drawdown_fraction",
            "data_source", "actual_contract_sizing",
        }
        missing = sorted(required - set(evidence))
        if missing:
            raise ValueError("missing validation evidence: " + ", ".join(missing))
        result = self.ledger.record_angelone_validation(
            generation,
            net_pnl=evidence["net_pnl"],
            trades=evidence["trades"],
            duration_seconds=evidence["duration_seconds"],
            max_drawdown_fraction=evidence["max_drawdown_fraction"],
            data_source=evidence["data_source"],
            actual_contract_sizing=evidence["actual_contract_sizing"],
            stale_quote_events=evidence.get("stale_quote_events", 0),
            risk_violations=evidence.get("risk_violations", 0),
        )
        result["live_orders_enabled"] = False
        result["requires_separate_operator_approval"] = True
        self._ensure_population()
        return result

    def status(self) -> dict[str, Any]:
        generations = []
        for key in sorted(self.ledger.state["generations"], key=int):
            generations.append(self.ledger.scorecard(int(key)))
        return {
            "active_generations": self.active_generations(),
            "generations": generations,
            "champion_generation": self.ledger.state.get("champion_generation"),
            "live_orders_enabled": False,
        }
