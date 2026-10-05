import math
from dataclasses import dataclass

@dataclass
class Position:
    market_id:str
    fraction:float
    side:str
    confidence:float

class PortfolioRisk:
    def __init__(self,max_position=.06,max_total_exposure=.18,max_daily_loss=.03):
        self.max_position=max_position
        self.max_total_exposure=max_total_exposure
        self.max_daily_loss=max_daily_loss
    def approve(self,new_fraction,positions,daily_pnl,correlated_ids=None):
        correlated_ids=correlated_ids or set()
        exposure=sum(abs(x.fraction) for x in positions)
        correlated=sum(abs(x.fraction) for x in positions if x.market_id in correlated_ids)
        if new_fraction<=0 or new_fraction>self.max_position:return False,"position_cap"
        if exposure+new_fraction>self.max_total_exposure:return False,"portfolio_exposure"
        if daily_pnl<=-self.max_daily_loss:return False,"daily_loss_limit"
        if correlated+new_fraction>self.max_total_exposure/2:return False,"correlation_cap"
        return True,"approved"
