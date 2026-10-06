"""Deterministic pre-trade debate for the NSE specialist agents.

This is an evidence-based debate layer, not a text-generation demo. Specialists
challenge opposing signals using the same computed market features. The final
supervisor decision can only approve a trade when qualified agents provide
enough directional evidence and the debate does not expose a material conflict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class DebateResult:
    decision: str
    direction: int
    score: float
    confidence: float
    agreement: float
    conflict: float
    rationale: str
    votes: Dict[str, float]
    challenges: List[str]


class NSEPreTradeDebate:
    """Run a deterministic specialist-vs-specialist debate before execution."""

    def __init__(self, min_agreement: float = 0.60, max_conflict: float = 0.45):
        self.min_agreement = min_agreement
        self.max_conflict = max_conflict

    @staticmethod
    def _label(value: float) -> str:
        if value > 0.05:
            return "BUY"
        if value < -0.05:
            return "SELL"
        return "NEUTRAL"

    def run(self, features: dict, votes: Dict[str, float], qualified: List[str]) -> DebateResult:
        usable = {
            agent: float(votes[agent])
            for agent in qualified
            if agent in votes and abs(float(votes[agent])) > 0.05
        }
        if len(usable) < 3:
            return DebateResult(
                "NO_TRADE", 0, 0.0, 0.0, 0.0, 1.0,
                "insufficient qualified specialists for debate",
                usable, [],
            )

        positive = sum(1 for v in usable.values() if v > 0)
        negative = sum(1 for v in usable.values() if v < 0)
        total = len(usable)
        majority_direction = 1 if positive >= negative else -1
        majority = max(positive, negative) / total
        conflict = min(positive, negative) / total
        weighted = sum(usable.values()) / total
        agreement = majority

        challenges = []
        labels = {a: self._label(v) for a, v in usable.items()}
        for agent, vote in usable.items():
            if vote * weighted < 0:
                challenges.append(
                    f"{agent} challenges the majority ({labels[agent]}) against "
                    f"the aggregate {self._label(weighted)} signal"
                )

        evidence = []
        if features.get("r5", 0) * majority_direction > 0:
            evidence.append("5-bar momentum supports the majority")
        if features.get("r20", 0) * majority_direction > 0:
            evidence.append("20-bar momentum supports the majority")
        if features.get("breakout", 0) * majority_direction > 0:
            evidence.append("breakout evidence supports the majority")
        if (features.get("volume_ratio", 1.0) - 1.0) * majority_direction > 0:
            evidence.append("volume pressure supports the majority")
        if features.get("reversion", 0) * majority_direction < 0:
            evidence.append("mean-reversion evidence supports the majority")

        # Require both a directional majority and a reasonably coherent debate.
        if agreement < self.min_agreement or conflict > self.max_conflict:
            decision = "NO_TRADE"
            direction = 0
        else:
            decision = "BUY" if majority_direction > 0 else "SELL"
            direction = majority_direction

        confidence = min(
            0.95,
            0.50
            + 0.25 * agreement
            + 0.15 * min(1.0, abs(weighted))
            + 0.05 * min(1.0, len(evidence) / 3.0),
        )
        rationale = (
            f"specialists={total}; BUY={positive}; SELL={negative}; "
            f"agreement={agreement:.2f}; conflict={conflict:.2f}; "
            f"aggregate={weighted:.3f}; evidence="
            + (", ".join(evidence) if evidence else "mixed")
        )
        return DebateResult(
            decision, direction, abs(weighted), confidence,
            agreement, conflict, rationale, usable, challenges,
        )
