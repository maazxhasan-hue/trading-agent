"""Deterministic pre-trade debate for specialist agents.

The debate layer is deliberately deterministic and auditable. It combines
out-of-sample learning weights with independent evidence checks, and can veto
a trade when market structure contradicts the majority.
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
    """Run a conservative specialist-vs-specialist debate."""

    def __init__(
        self,
        min_agreement: float = 0.60,
        max_conflict: float = 0.45,
        min_evidence: float = 0.0,
        max_volatility: float = 0.08,
    ):
        self.min_agreement = min_agreement
        self.max_conflict = max_conflict
        self.min_evidence = min_evidence
        self.max_volatility = max_volatility

    @staticmethod
    def _label(value: float) -> str:
        if value > 0.05:
            return "BUY"
        if value < -0.05:
            return "SELL"
        return "NEUTRAL"

    def run(
        self,
        features: dict,
        votes: Dict[str, float],
        qualified: List[str],
        weights: Dict[str, float] | None = None,
    ) -> DebateResult:
        weights = weights or {}
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

        # Learning changes influence, never eligibility. Bounds prevent a
        # temporarily lucky agent from dominating the committee.
        bounded_weights = {
            a: max(0.70, min(1.30, float(weights.get(a, 1.0))))
            for a in usable
        }
        total_weight = sum(bounded_weights.values())
        weighted_votes = {
            a: usable[a] * bounded_weights[a] for a in usable
        }
        weighted = sum(weighted_votes.values()) / max(total_weight, 1e-9)

        positive_weight = sum(
            bounded_weights[a] for a, v in usable.items() if v > 0
        )
        negative_weight = sum(
            bounded_weights[a] for a, v in usable.items() if v < 0
        )
        majority_direction = 1 if positive_weight >= negative_weight else -1
        majority = max(positive_weight, negative_weight) / max(total_weight, 1e-9)
        conflict = min(positive_weight, negative_weight) / max(total_weight, 1e-9)
        agreement = majority

        challenges = []
        labels = {a: self._label(v) for a, v in usable.items()}
        for agent, vote in usable.items():
            if vote * weighted < 0:
                challenges.append(
                    f"{agent} challenges the majority ({labels[agent]}) against "
                    f"the weighted aggregate {self._label(weighted)} signal"
                )

        evidence = []
        if features.get("r5", 0) * majority_direction > 0:
            evidence.append("5-bar momentum")
        if features.get("r20", 0) * majority_direction > 0:
            evidence.append("20-bar momentum")
        if features.get("breakout", 0) * majority_direction > 0:
            evidence.append("breakout")
        if (features.get("volume_ratio", 1.0) - 1.0) * majority_direction > 0:
            evidence.append("volume pressure")
        if features.get("reversion", 0) * majority_direction < 0:
            evidence.append("mean-reversion alignment")
        if features.get("trend_quality", 0) * majority_direction > 0:
            evidence.append("trend quality")
        if features.get("range_ratio", 1.0) < 1.8:
            evidence.append("controlled range")

        # A strong directional vote with no supporting market evidence is not
        # enough. This is especially important when several technical agents
        # share the same noisy input.
        evidence_score = min(1.0, len(evidence) / 4.0)
        structural_veto = False
        veto_reason = ""

        if features.get("data_quality", 1.0) < 0.70:
            structural_veto = True
            veto_reason = "poor data quality"
        elif features.get("liquidity_score", 1.0) < 0.35:
            structural_veto = True
            veto_reason = "weak liquidity"
        elif features.get("volatility_ratio", 1.0) > self.max_volatility:
            structural_veto = True
            veto_reason = "extreme volatility"
        elif (
            abs(features.get("trend_gap", 0.0)) > 0.0
            and features.get("rsi", 50.0) > 78
            and majority_direction > 0
        ):
            structural_veto = True
            veto_reason = "overbought trend chase"
        elif features.get("rsi", 50.0) < 22 and majority_direction < 0:
            structural_veto = True
            veto_reason = "oversold trend chase"

        if agreement < self.min_agreement or conflict > self.max_conflict:
            decision = "NO_TRADE"
            direction = 0
        elif structural_veto:
            decision = "NO_TRADE"
            direction = 0
            challenges.append("risk veto: " + veto_reason)
        elif evidence_score < self.min_evidence:
            decision = "NO_TRADE"
            direction = 0
            challenges.append("evidence quorum not met")
        else:
            decision = "BUY" if majority_direction > 0 else "SELL"
            direction = majority_direction

        confidence = min(
            0.95,
            max(
                0.0,
                0.48
                + 0.28 * agreement
                + 0.14 * min(1.0, abs(weighted))
                + 0.10 * evidence_score
                - 0.12 * conflict,
            ),
        )
        if structural_veto:
            confidence = min(confidence, 0.49)

        rationale = (
            f"specialists={len(usable)}; BUY={sum(v > 0 for v in usable.values())}; "
            f"SELL={sum(v < 0 for v in usable.values())}; "
            f"agreement={agreement:.2f}; conflict={conflict:.2f}; "
            f"weighted={weighted:.3f}; evidence={evidence_score:.2f}; "
            f"support=" + (", ".join(evidence) if evidence else "none")
        )
        if veto_reason:
            rationale += f"; veto={veto_reason}"

        return DebateResult(
            decision, direction, abs(weighted), confidence,
            agreement, conflict, rationale, weighted_votes, challenges,
        )
