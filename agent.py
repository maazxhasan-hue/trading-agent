#!/usr/bin/env python3
"""Runnable multi-agent paper trading engine."""
import csv, math, os, statistics, time, json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List
import requests
from market_data import markets, price_history

SCAN_SECONDS = 300
MAX_MARKETS = 1000
EDGE_MIN = 0.08
CONFIDENCE_MIN = 0.80
MAX_POSITION = 0.06
START_BANKROLL = 1000.0

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "TradingCompanyAgent/1.0"})

@dataclass
class Market:
    market_id: str
    question: str
    yes_price: float
    volume: float
    liquidity: float

@dataclass
class Proposal:
    market: Market
    fair_value: float
    edge: float
    confidence: float
    side: str
    position_fraction: float
    votes: dict
    reason: str

class PolymarketPublicFeed:
    URL = "https://gamma-api.polymarket.com/markets"
    def fetch(self, limit=MAX_MARKETS) -> List[Market]:
        try:
            r = SESSION.get(self.URL, params={"active":"true","closed":"false","limit":min(limit,1000)}, timeout=20)
            r.raise_for_status()
            rows = r.json()
        except Exception as exc:
            print("[feed] unavailable:", exc)
            return []
        markets = []
        for row in rows:
            try:
                prices = row.get("outcomePrices")
                if isinstance(prices, str):
                    prices = json.loads(prices)
                if not prices:
                    continue
                p = float(prices[0])
                if not 0.01 < p < 0.99:
                    continue
                markets.append(Market(
                    str(row.get("id") or row.get("conditionId") or ""),
                    str(row.get("question") or "Unknown market"),
                    p,
                    float(row.get("volume") or 0),
                    float(row.get("liquidity") or 0),
                ))
            except (TypeError, ValueError, KeyError, json.JSONDecodeError):
                continue
        return markets[:limit]

class FairValueAgent:
    def estimate(self, m):
        p = m.yes_price
        # Explicit bounded mean-reversion prior. This is a heuristic, not truth.
        # It can generate candidates, but every candidate still needs debate/risk gates.
        fair = max(0.01, min(0.99, 0.5 + 0.70 * (p - 0.5)))
        confidence = 0.80 if abs(p - 0.5) >= 0.20 else 0.74
        return fair, confidence

class StrategyAgent:
    def __init__(self, name): self.name = name
    def vote(self, m, fair):
        edge = fair - m.yes_price
        if abs(edge) < 0.01: return 0.0
        return max(-1.0, min(1.0, edge / 0.10))

class RiskAgent:
    def approve(self, p, bankroll):
        return (
            p.confidence >= CONFIDENCE_MIN and
            abs(p.edge) >= EDGE_MIN and
            0 < p.position_fraction <= MAX_POSITION and
            p.market.liquidity > 0 and
            bankroll > 0
        )

class TradingCompany:
    def __init__(self):
        self.bankroll = START_BANKROLL
        self.feed = PolymarketPublicFeed()
        self.fair = FairValueAgent(self.feed)
        self.strategies = [StrategyAgent(x) for x in [
            "momentum","mean_reversion","event_driven","crypto_specialist","x_social_research"
        ]]
        self.risk = RiskAgent()
        self.log = "paper_trades.csv"
        if not os.path.exists(self.log):
            with open(self.log,"w",newline="",encoding="utf-8") as f:
                csv.writer(f).writerow([
                    "time","market_id","question","side","price","fair_value",
                    "edge","confidence","position_fraction","stake","decision"
                ])

    def kelly(self, price, fair):
        if not 0 < price < 1: return 0.0
        p = max(0.001,min(0.999,fair))
        q = 1-p
        b = (1-price)/price
        if b <= 0: return 0.0
        raw = ((b*p)-q)/b
        return max(0.0,min(MAX_POSITION,raw*0.25))

    def debate(self, m, fair):
        votes = {a.name:a.vote(m,fair) for a in self.strategies}
        avg = statistics.mean(votes.values())
        spread = statistics.pstdev(votes) if len(votes)>1 else 0
        agreement = 1-min(1,spread)
        confidence = min(0.99,0.50+0.30*agreement+0.20*min(1,abs(avg)))
        return votes, confidence

    def evaluate(self,m):
        fair, base_conf = self.fair.estimate(m)
        edge = fair-m.yes_price
        if abs(edge) < EDGE_MIN: return None
        votes, debate_conf = self.debate(m,fair)
        confidence = min(base_conf,debate_conf)
        side = "BUY_YES" if edge>0 else "BUY_NO"
        price = m.yes_price if side=="BUY_YES" else 1-m.yes_price
        fv = fair if side=="BUY_YES" else 1-fair
        fraction = self.kelly(price,fv)
        return Proposal(m,fair,edge,confidence,side,fraction,votes,"multi-agent paper decision")

    def paper_order(self,p):
        stake = self.bankroll*p.position_fraction
        with open(self.log,"a",newline="",encoding="utf-8") as f:
            csv.writer(f).writerow([
                datetime.now(timezone.utc).isoformat(),p.market.market_id,p.market.question,
                p.side,p.market.yes_price,p.fair_value,p.edge,p.confidence,
                p.position_fraction,stake,"PAPER_ORDER"
            ])
        print("[PAPER]",p.side,"edge=%.2f%%"%(p.edge*100),
              "confidence=%.2f%%"%(p.confidence*100),
              "stake=%.2f"%stake)

    def cycle(self):
        print("\n["+datetime.now().isoformat(timespec="seconds")+"] scanning...")
        markets = self.feed.fetch(MAX_MARKETS)
        print("[scan] markets:",len(markets))
        candidates=[]
        for m in markets:
            p=self.evaluate(m)
            if p and self.risk.approve(p,self.bankroll):
                candidates.append(p)
        candidates.sort(key=lambda p:abs(p.edge)*p.confidence,reverse=True)
        print("[decision] passing all gates:",len(candidates))
        if candidates:
            self.paper_order(candidates[0])
        else:
            print("[decision] no trade")

    def run(self):
        print("Trading Company Agent — PAPER MODE")
        while True:
            try: self.cycle()
            except KeyboardInterrupt:
                print("Stopped."); return
            except Exception as exc:
                print("[engine] recovered:",exc)
            time.sleep(SCAN_SECONDS)

if __name__=="__main__":
    TradingCompany().run()
