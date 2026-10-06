"""NSE market-regime classifier based only on supplied OHLC-derived features."""
from dataclasses import dataclass

@dataclass(frozen=True)
class MarketRegime:
    name: str
    direction: int
    confidence: float
    reasons: tuple[str, ...]

def classify(features: dict) -> MarketRegime:
    r5=float(features.get("r5",0)); r20=float(features.get("r20",0))
    vol=float(features.get("vol",0)); breakout=float(features.get("breakout",0))
    volume=float(features.get("volume_ratio",1))
    reasons=[]
    trend=(r5+r20)/2
    if trend > max(vol*1.5,0.001):
        direction=1; name="TRENDING_UP"; reasons.append("positive short/intermediate momentum")
    elif trend < -max(vol*1.5,0.001):
        direction=-1; name="TRENDING_DOWN"; reasons.append("negative short/intermediate momentum")
    else:
        direction=0; name="SIDEWAYS"; reasons.append("momentum is not directional")
    if vol > 0.015:
        name="HIGH_VOLATILITY" if direction==0 else name+"_HIGH_VOL"
        reasons.append("elevated realized volatility")
    elif vol < 0.004:
        reasons.append("low realized volatility")
    if abs(breakout) > max(vol,0.001):
        reasons.append("breakout magnitude exceeds volatility baseline")
    if volume >= 1.5:
        reasons.append("volume expansion")
    confidence=min(0.95,0.50+0.20*min(1,abs(trend)/max(vol,0.001))+0.10*min(1,abs(breakout)/max(vol,0.001)))
    return MarketRegime(name,direction,confidence,tuple(reasons))
