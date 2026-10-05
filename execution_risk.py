"""Deterministic portfolio safety controls used before execution.

These controls are deliberately conservative: they can reject or reduce a trade,
but they cannot increase a requested size.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    fraction: float
    reason: str


class ExecutionRiskGate:
    def __init__(
        self,
        max_position=0.06,
        max_slippage=0.02,
        min_book_depth_multiple=2.0,
        kill_switch=False,
    ):
        self.max_position = max_position
        self.max_slippage = max_slippage
        self.min_book_depth_multiple = min_book_depth_multiple
        self.kill_switch = kill_switch

    def approve(
        self,
        requested_fraction,
        bankroll,
        order_price,
        best_ask,
        book_depth,
        daily_pnl,
        daily_loss_limit=0.03,
    ):
        if self.kill_switch:
            return RiskDecision(False, 0.0, "kill_switch")
        if bankroll <= 0:
            return RiskDecision(False, 0.0, "invalid_bankroll")
        if requested_fraction <= 0:
            return RiskDecision(False, 0.0, "non_positive_size")
        fraction = min(requested_fraction, self.max_position)
        if daily_pnl < -(bankroll * daily_loss_limit):
            return RiskDecision(False, 0.0, "daily_loss_limit")
        if not 0 < order_price < 1:
            return RiskDecision(False, 0.0, "invalid_price")
        if best_ask is not None and best_ask > 0:
            slippage = max(0.0, (best_ask - order_price) / best_ask)
            if slippage > self.max_slippage:
                return RiskDecision(False, 0.0, "slippage_limit")
        stake = bankroll * fraction
        required_depth = (stake / max(order_price, 0.001)) * self.min_book_depth_multiple
        if book_depth < required_depth:
            return RiskDecision(False, 0.0, "insufficient_book_depth")
        return RiskDecision(True, fraction, "approved")
