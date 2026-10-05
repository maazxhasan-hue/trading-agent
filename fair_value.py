"""Bounded fair-value model for binary prediction-market research.

This is a research model only. It does not guarantee outcomes and does not
place orders. External evidence modifies confidence more than probability.
"""
from dataclasses import dataclass
import statistics

def clamp(x, lo=0.01, hi=0.99):
    return max(lo, min(hi, float(x)))

@dataclass
class FairValueResult:
    value: float
    confidence: float
    uncertainty: float
    components: dict

class FairValueModel:
    def estimate(
        self, current, history_fair, history_confidence, volatility,
        book_imbalance=0.0, cross_market_score=0.0,
        news_score=0.0, macro_score=0.0, crypto_score=0.0,
        social_score=0.0, history=None,
    ):
        current = clamp(current)
        history_fair = clamp(history_fair)
        vol_penalty = min(0.25, max(0.0, volatility * 2.5))
        robust = history_fair
        if history:
            values = [float(x) for x in history if 0.0 < float(x) < 1.0]
            if len(values) >= 5:
                values.sort()
                trim = max(1, len(values) // 10)
                trimmed = values[trim:-trim] if len(values) > 2 * trim else values
                robust = statistics.median(trimmed)
        book_adj = max(-0.035, min(0.035, 0.035 * book_imbalance))
        cross_adj = max(-0.025, min(0.025, 0.025 * cross_market_score))
        fair = (
            0.48 * robust + 0.27 * current +
            0.15 * (current + book_adj) +
            0.10 * (current + cross_adj)
        )
        evidence_strength = (
            0.20 * abs(book_imbalance) + 0.15 * abs(cross_market_score) +
            0.10 * abs(news_score) + 0.10 * abs(macro_score) +
            0.08 * abs(crypto_score) + 0.05 * abs(social_score)
        )
        confidence = (
            0.45 * history_confidence +
            0.35 * (0.80 - vol_penalty) +
            0.20 * min(0.95, 0.55 + evidence_strength)
        )
        confidence = max(0.50, min(0.95, confidence))
        uncertainty = max(0.01, min(0.50, 1.0 - confidence + vol_penalty))
        return FairValueResult(
            clamp(fair), confidence, uncertainty,
            {
                "historical": robust, "market": current,
                "book_adjustment": book_adj,
                "cross_market_adjustment": cross_adj,
                "volatility": volatility,
                "evidence_strength": evidence_strength,
            },
        )
