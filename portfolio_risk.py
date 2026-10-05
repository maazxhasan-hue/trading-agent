"""Portfolio exposure and correlation guardrails for paper trading."""
from dataclasses import dataclass
import re

@dataclass
class Position:
    market_id: str
    fraction: float
    side: str
    confidence: float
    question: str = ""

class PortfolioRisk:
    def __init__(self, max_position=.06, max_total_exposure=.18,
                 max_daily_loss=.03, max_correlated_exposure=.09):
        self.max_position = max_position
        self.max_total_exposure = max_total_exposure
        self.max_daily_loss = max_daily_loss
        self.max_correlated_exposure = max_correlated_exposure

    @staticmethod
    def _terms(question):
        stop = {"will","what","when","where","which","the","and","for","this",
                "that","from","with","have","has","yes","no"}
        return {
            x for x in re.findall(r"[a-z0-9]{4,}", (question or "").lower())
            if x not in stop
        }

    def correlated(self, question, positions):
        terms = self._terms(question)
        ids = set()
        for p in positions:
            other = self._terms(getattr(p, "question", ""))
            if terms and other:
                overlap = len(terms & other) / max(1, len(terms | other))
                if overlap >= 0.30:
                    ids.add(p.market_id)
        return ids

    def approve(self, new_fraction, positions, daily_pnl,
                correlated_ids=None, bankroll=1.0):
        correlated_ids = correlated_ids or set()
        exposure = sum(abs(x.fraction) for x in positions)
        correlated = sum(
            abs(x.fraction) for x in positions
            if x.market_id in correlated_ids
        )
        daily_loss_fraction = abs(min(0.0, daily_pnl)) / max(bankroll, 1e-9)
        if new_fraction <= 0 or new_fraction > self.max_position:
            return False, "position_cap"
        if exposure + new_fraction > self.max_total_exposure:
            return False, "portfolio_exposure"
        if daily_loss_fraction > self.max_daily_loss:
            return False, "daily_loss_limit"
        if correlated + new_fraction > self.max_correlated_exposure:
            return False, "correlation_cap"
        return True, "approved"
