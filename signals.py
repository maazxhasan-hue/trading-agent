import statistics
from dataclasses import dataclass
@dataclass
class Signal:
    fair:float; edge:float; confidence:float; side:str; reasons:list
def clamp(x,a=0.001,b=0.999): return max(a,min(b,x))
def momentum(history):
    if len(history)<8:return 0.0
    p=[float(x["p"]) for x in history[-30:]]
    return p[-1]-p[-8]
def mean_reversion(history):
    if len(history)<12:return 0.0
    p=[float(x["p"]) for x in history[-30:]]
    return statistics.mean(p)-p[-1]
def fair_value(current,history):
    if not history:return current,0.50
    p=[float(x["p"]) for x in history[-50:]]
    med=statistics.median(p); mom=momentum(history); rev=mean_reversion(history)
    fair=clamp(0.65*med+0.20*(current+mom)+0.15*(current+rev))
    vol=statistics.pstdev(p) if len(p)>2 else 0.0
    conf=max(0.50,min(0.96,0.90-2.0*vol))
    return fair,conf
def build_signal(current,history):
    fair,conf=fair_value(current,history); edge=fair-current
    return Signal(fair,edge,conf,"YES" if edge>0 else "NO",["historical median","momentum/reversion ensemble","volatility-adjusted confidence"])
