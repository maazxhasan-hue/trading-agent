"""Pure portfolio-risk guards used before any order request."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str

def exposure_check(capital, positions, price, qty, max_fraction=0.30, max_position_fraction=0.06):
    capital=float(capital); price=float(price); qty=int(qty)
    if capital<=0 or price<=0 or qty<=0:
        return RiskDecision(False,"invalid capital/price/quantity")
    existing=sum(abs(float(p.get("entry",0))*int(p.get("qty",0))) for p in positions)
    order_value=price*qty
    if order_value>capital*max_position_fraction:
        return RiskDecision(False,"per-position exposure cap")
    if existing+order_value>capital*max_fraction:
        return RiskDecision(False,"portfolio exposure cap")
    return RiskDecision(True,"ok")

def drawdown_check(equity, peak, max_drawdown=0.10):
    if peak<=0: return RiskDecision(False,"invalid peak equity")
    dd=max(0.0,1.0-float(equity)/float(peak))
    return RiskDecision(dd<max_drawdown, "portfolio drawdown kill switch" if dd>=max_drawdown else "ok")
