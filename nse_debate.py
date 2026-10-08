"""Deterministic, adaptive pre-trade debate for specialist agents.

Each specialist receives a bounded context-fit weight based on the evidence it
is designed to interpret. Historical learning weights can further adjust that
influence. The layer remains auditable and can veto structurally unsafe trades.
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
    def __init__(self, min_agreement: float = 0.60, max_conflict: float = 0.45,
                 min_evidence: float = 0.0, max_volatility: float = 0.08):
        self.min_agreement = min_agreement
        self.max_conflict = max_conflict
        self.min_evidence = min_evidence
        self.max_volatility = max_volatility

    @staticmethod
    def _label(value: float) -> str:
        return "BUY" if value > 0.05 else "SELL" if value < -0.05 else "NEUTRAL"

    @staticmethod
    def _context_weight(agent: str, f: dict, direction: int) -> float:
        name = agent.lower()
        trend = abs(float(f.get("trend_gap", 0.0)))
        momentum = abs(float(f.get("r10", 0.0))) + abs(float(f.get("r20", 0.0)))
        reversion = abs(float(f.get("reversion", 0.0)))
        breakout = abs(float(f.get("breakout", 0.0))) + abs(float(f.get("breakdown", 0.0)))
        volume = min(2.0, abs(float(f.get("volume_ratio", 1.0)) - 1.0))
        range_expansion = min(2.0, abs(float(f.get("range_ratio", 1.0)) - 1.0))
        fit = 1.0
        if "momentum" in name:
            fit += min(0.20, momentum * 8.0 + trend * 4.0)
        elif "mean_reversion" in name:
            fit += min(0.20, reversion * 8.0)
            if trend > 0.015:
                fit -= 0.08
        elif "event" in name:
            fit += min(0.20, breakout * 8.0 + volume * 0.06 + range_expansion * 0.04)
        elif "mcx_commodity" in name:
            fit += min(0.25, volume * 0.08 + range_expansion * 0.08 + momentum * 2.0)
        elif "cross_market" in name:
            fit += min(0.18, abs(float(f.get("r3", 0.0)) - 0.25 * float(f.get("r20", 0.0))) * 8.0)
        if direction and trend > 0.03:
            trend_direction = 1 if f.get("trend_gap", 0.0) > 0 else -1
            if direction != trend_direction and "mean_reversion" not in name:
                fit -= 0.10
        return max(0.70, min(1.30, fit))

    def run(self, features: dict, votes: Dict[str, float], qualified: List[str],
            weights: Dict[str, float] | None = None) -> DebateResult:
        weights = weights or {}
        usable = {agent: float(votes[agent]) for agent in qualified
                  if agent in votes and abs(float(votes[agent])) > 0.05}
        if len(usable) < 3:
            return DebateResult("NO_TRADE", 0, 0.0, 0.0, 0.0, 1.0,
                                "insufficient qualified specialists for debate", usable, [])

        bounded_weights = {}
        for agent, vote in usable.items():
            learned = max(0.70, min(1.30, float(weights.get(agent, 1.0))))
            contextual = self._context_weight(agent, features, 1 if vote > 0 else -1)
            bounded_weights[agent] = max(0.70, min(1.30, learned * contextual))
        total_weight = sum(bounded_weights.values())
        weighted_votes = {a: usable[a] * bounded_weights[a] for a in usable}
        weighted = sum(weighted_votes.values()) / max(total_weight, 1e-9)
        positive_weight = sum(bounded_weights[a] for a, v in usable.items() if v > 0)
        negative_weight = sum(bounded_weights[a] for a, v in usable.items() if v < 0)
        majority_direction = 1 if positive_weight >= negative_weight else -1
        agreement = max(positive_weight, negative_weight) / max(total_weight, 1e-9)
        conflict = min(positive_weight, negative_weight) / max(total_weight, 1e-9)

        challenges = []
        for agent, vote in usable.items():
            if vote * weighted < 0:
                challenges.append(f"{agent} challenges the weighted aggregate ({self._label(vote)})")

        evidence = []
        if features.get("r5", 0) * majority_direction > 0: evidence.append("5-bar momentum")
        if features.get("r20", 0) * majority_direction > 0: evidence.append("20-bar momentum")
        if features.get("breakout", 0) * majority_direction > 0: evidence.append("breakout")
        if (features.get("volume_ratio", 1.0) - 1.0) * majority_direction > 0: evidence.append("volume pressure")
        if features.get("reversion", 0) * majority_direction < 0: evidence.append("mean-reversion alignment")
        if features.get("trend_quality", 0) * majority_direction > 0: evidence.append("trend quality")
        if features.get("range_ratio", 1.0) < 1.8: evidence.append("controlled range")
        evidence_score = min(1.0, len(evidence) / 4.0)

        structural_veto = False
        veto_reason = ""
        if features.get("data_quality", 1.0) < 0.70:
            structural_veto, veto_reason = True, "poor data quality"
        elif features.get("liquidity_score", 1.0) < 0.35:
            structural_veto, veto_reason = True, "weak liquidity"
        elif features.get("volatility_ratio", 1.0) > self.max_volatility:
            structural_veto, veto_reason = True, "extreme volatility"
        elif features.get("rsi", 50.0) > 78 and majority_direction > 0:
            structural_veto, veto_reason = True, "overbought trend chase"
        elif features.get("rsi", 50.0) < 22 and majority_direction < 0:
            structural_veto, veto_reason = True, "oversold trend chase"

        if agreement < self.min_agreement or conflict > self.max_conflict:
            decision, direction = "NO_TRADE", 0
        elif structural_veto:
            decision, direction = "NO_TRADE", 0
            challenges.append("risk veto: " + veto_reason)
        elif evidence_score < self.min_evidence:
            decision, direction = "NO_TRADE", 0
            challenges.append("evidence quorum not met")
        else:
            decision, direction = ("BUY", 1) if majority_direction > 0 else ("SELL", -1)

        confidence = min(0.95, max(0.0,
            0.48 + 0.28 * agreement + 0.14 * min(1.0, abs(weighted))
            + 0.10 * evidence_score - 0.12 * conflict))
        if structural_veto:
            confidence = min(confidence, 0.49)
        rationale = (
            f"specialists={len(usable)}; BUY={sum(v > 0 for v in usable.values())}; "
            f"SELL={sum(v < 0 for v in usable.values())}; agreement={agreement:.2f}; "
            f"conflict={conflict:.2f}; weighted={weighted:.3f}; evidence={evidence_score:.2f}; "
            f"support=" + (", ".join(evidence) if evidence else "none"))
        if veto_reason:
            rationale += f"; veto={veto_reason}"
        return DebateResult(decision, direction, abs(weighted), confidence,
                            agreement, conflict, rationale, weighted_votes, challenges)
