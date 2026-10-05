#!/usr/bin/env python3
"""Adaptive multi-agent paper trading engine.

The engine is deliberately paper-only. It scans, debates, risk-checks, opens a
paper position, settles it from the public market feed, diagnoses losses, and
quarantines/evolves the supporting strategy agents.
"""
import csv
import json
import math
import os
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

import requests

from agent_lifecycle import AgentLifecycleManager
from market_data import price_history
from portfolio_risk import PortfolioRisk, Position
from calibration import CalibrationTracker


SCAN_SECONDS = 300
MAX_MARKETS = 1000
EDGE_MIN = 0.08
CONFIDENCE_MIN = 0.80
MAX_POSITION = 0.06
START_BANKROLL = 1000.0
SETTLE_AFTER_SECONDS = 300

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "TradingCompanyAgent/2.0"})


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
    supporting_agents: list


@dataclass
class OpenTrade:
    proposal: Proposal
    entry_yes_price: float
    opened_at: float
    stake: float


class PolymarketPublicFeed:
    URL = "https://gamma-api.polymarket.com/markets"

    def fetch(self, limit=MAX_MARKETS) -> List[Market]:
        try:
            response = SESSION.get(
                self.URL,
                params={"active": "true", "closed": "false",
                        "limit": min(limit, 1000)},
                timeout=20,
            )
            response.raise_for_status()
            rows = response.json()
        except Exception as exc:
            print("[feed] unavailable:", exc)
            return []

        result = []
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
                result.append(Market(
                    str(row.get("id") or row.get("conditionId") or ""),
                    str(row.get("question") or "Unknown market"),
                    p,
                    float(row.get("volume") or 0),
                    float(row.get("liquidity") or 0),
                ))
            except (TypeError, ValueError, KeyError, json.JSONDecodeError):
                continue
        return result[:limit]

    def current_price(self, market_id):
        for market in self.fetch(MAX_MARKETS):
            if market.market_id == market_id:
                return market.yes_price
        return None


class FairValueAgent:
    """Bounded prior used only as a candidate generator, never as truth."""

    def estimate(self, market):
        p = market.yes_price
        # Pull the estimate toward the center. This intentionally avoids
        # pretending that the public price itself is a reliable fair value.
        fair = max(0.01, min(0.99, 0.5 + 0.70 * (p - 0.5)))
        confidence = 0.80 if abs(p - 0.5) >= 0.20 else 0.74
        return fair, confidence


class StrategyAgent:
    def __init__(self, agent_id, name, version=1, mutation=""):
        self.agent_id = agent_id
        self.name = name
        self.version = version
        self.mutation = mutation

    def vote(self, market, fair):
        edge = fair - market.yes_price
        if abs(edge) < 0.01:
            return 0.0

        # Strategy diversity is deterministic and bounded. Replacements change
        # their sensitivity rather than blindly repeating the failed thesis.
        sensitivity = {
            "momentum": 1.00,
            "mean_reversion": 0.90,
            "event_driven": 0.75,
            "crypto_specialist": 0.85,
            "x_social_research": 0.65,
            "cross_market_arbitrage": 0.80,
        }.get(self.name, 0.70)

        if self.mutation == "regime_shift":
            sensitivity *= 0.65
        elif self.mutation == "fair_value_error":
            sensitivity *= 0.55
        elif self.mutation == "liquidity":
            sensitivity *= 0.70
        elif self.mutation == "data_staleness":
            sensitivity *= 0.50

        return max(-1.0, min(1.0, edge / (0.10 / max(0.25, sensitivity))))


class RiskAgent:
    def approve(self, proposal, bankroll):
        return (
            proposal.confidence >= CONFIDENCE_MIN
            and abs(proposal.edge) >= EDGE_MIN
            and 0 < proposal.position_fraction <= MAX_POSITION
            and proposal.market.liquidity > 0
            and bankroll > 0
        )


class TradingCompany:
    def __init__(self):
        self.bankroll = START_BANKROLL
        self.feed = PolymarketPublicFeed()
        self.fair = FairValueAgent()
        self.risk = RiskAgent()
        self.portfolio_risk = PortfolioRisk()
        self.calibration = CalibrationTracker()
        self.lifecycle = AgentLifecycleManager()
        self.positions = []
        self.open_trades = []
        self.daily_pnl = 0.0
        self.log = "paper_trades.csv"

        strategy_names = [
            "momentum", "mean_reversion", "event_driven",
            "crypto_specialist", "x_social_research",
            "cross_market_arbitrage",
        ]
        self.strategies = []
        for name in strategy_names:
            state = self.lifecycle.ensure(name + "-v1", name)
            self.strategies.append(
                StrategyAgent(state.agent_id, name, state.version)
            )

        if not os.path.exists(self.log):
            with open(self.log, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    "time", "market_id", "question", "side", "entry",
                    "settle", "fair_value", "edge", "confidence",
                    "position_fraction", "stake", "pnl", "decision",
                    "failure_reason", "supporting_agents",
                ])

    def kelly(self, price, fair):
        if not 0 < price < 1:
            return 0.0
        p = max(0.001, min(0.999, fair))
        q = 1 - p
        b = (1 - price) / price
        if b <= 0:
            return 0.0
        raw = ((b * p) - q) / b
        return max(0.0, min(MAX_POSITION, raw * 0.25))

    def debate(self, market, fair):
        votes = {a.agent_id: a.vote(market, fair) for a in self.strategies}
        active_votes = list(votes.values())
        avg = statistics.mean(active_votes)
        spread = statistics.pstdev(active_votes) if len(active_votes) > 1 else 0
        agreement = 1 - min(1, spread)
        confidence = min(0.99, 0.50 + 0.30 * agreement
                         + 0.20 * min(1, abs(avg)))
        return votes, confidence

    def evaluate(self, market):
        fair, base_conf = self.fair.estimate(market)
        edge = fair - market.yes_price
        if abs(edge) < EDGE_MIN:
            return None

        votes, debate_conf = self.debate(market, fair)
        confidence = min(base_conf, debate_conf)
        side = "BUY_YES" if edge > 0 else "BUY_NO"
        price = market.yes_price if side == "BUY_YES" else 1 - market.yes_price
        fv = fair if side == "BUY_YES" else 1 - fair
        fraction = self.kelly(price, fv)

        return Proposal(
            market=market,
            fair_value=fair,
            edge=edge,
            confidence=confidence,
            side=side,
            position_fraction=fraction,
            votes=votes,
            reason="multi-agent adaptive paper decision",
            supporting_agents=list(votes.keys()),
        )

    def paper_order(self, proposal):
        stake = self.bankroll * proposal.position_fraction
        trade = OpenTrade(
            proposal=proposal,
            entry_yes_price=proposal.market.yes_price,
            opened_at=time.time(),
            stake=stake,
        )
        self.open_trades.append(trade)
        self.positions.append(
            Position(
                proposal.market.market_id,
                proposal.position_fraction,
                proposal.side,
                proposal.confidence,
            )
        )
        print("[PAPER OPEN]", proposal.side,
              "edge=%.2f%%" % (proposal.edge * 100),
              "confidence=%.2f%%" % (proposal.confidence * 100),
              "stake=%.2f" % stake)

    def diagnose(self, trade, settle_price):
        p = trade.proposal
        move = settle_price - trade.entry_yes_price
        correct = (p.side == "BUY_YES" and move > 0) or (
            p.side == "BUY_NO" and move < 0
        )
        if correct:
            return True, "none"

        abs_move = abs(move)
        if abs_move < 0.01:
            return False, "noise"
        if p.confidence >= 0.90 and abs(p.edge) >= 0.15:
            return False, "fair_value_error"
        if p.confidence >= 0.85:
            return False, "regime_shift"
        if trade.proposal.market.liquidity < trade.stake * 2:
            return False, "liquidity"
        return False, "thesis_failure"

    def validate_replacement(self, reason):
        # Deterministic safety gate. A replacement starts at 0.60 and receives
        # a small uplift only when it has a meaningful mutation. This prevents
        # instant reactivation after a loss.
        base = {
            "fair_value_error": 0.68,
            "regime_shift": 0.64,
            "liquidity": 0.62,
            "data_staleness": 0.60,
            "thesis_failure": 0.59,
            "noise": 0.57,
        }.get(reason, 0.56)
        return base

    def adapt_after_loss(self, trade, reason):
        ids = trade.proposal.supporting_agents
        score = self.validate_replacement(reason)
        replacements = self.lifecycle.replace_after_loss(ids, reason, score)
        if not replacements:
            print("[ADAPT] no replacement passed validation:", reason)
            self.strategies = [
                a for a in self.strategies
                if a.agent_id not in ids
            ]
            return

        replacement_ids = {x.agent_id for x in replacements}
        survivors = [a for a in self.strategies if a.agent_id not in ids]
        for child in replacements:
            survivors.append(
                StrategyAgent(
                    child.agent_id,
                    child.base_strategy,
                    child.version,
                    reason,
                )
            )
        self.strategies = survivors
        print("[ADAPT] quarantined:", ", ".join(ids))
        print("[ADAPT] activated:", ", ".join(replacement_ids),
              "validation=%.2f" % score)

    def settle_due_trades(self):
        now = time.time()
        remaining = []
        for trade in self.open_trades:
            if now - trade.opened_at < SETTLE_AFTER_SECONDS:
                remaining.append(trade)
                continue

            settle = self.feed.current_price(trade.proposal.market.market_id)
            if settle is None:
                remaining.append(trade)
                continue

            won, reason = self.diagnose(trade, settle)
            # Binary-market paper P&L approximation. No live order is sent.
            entry = (trade.entry_yes_price if trade.proposal.side == "BUY_YES"
                     else 1 - trade.entry_yes_price)
            final = settle if trade.proposal.side == "BUY_YES" else 1 - settle
            pnl = trade.stake * ((final - entry) / max(entry, 0.001))
            self.daily_pnl += pnl

            with open(self.log, "a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    datetime.now(timezone.utc).isoformat(),
                    trade.proposal.market.market_id,
                    trade.proposal.market.question,
                    trade.proposal.side,
                    trade.entry_yes_price,
                    settle,
                    trade.proposal.fair_value,
                    trade.proposal.edge,
                    trade.proposal.confidence,
                    trade.proposal.position_fraction,
                    trade.stake,
                    pnl,
                    "PAPER_SETTLED",
                    reason,
                    "|".join(trade.proposal.supporting_agents),
                ])

            for agent_id in trade.proposal.supporting_agents:
                self.calibration.record(
                    agent_id, trade.proposal.confidence, won
                )

            self.bankroll += pnl
            print("[PAPER SETTLE]", "WIN" if won else "LOSS",
                  "pnl=%.2f" % pnl, "reason=", reason)

            if not won:
                # Kill/quarantine the failed decision makers, learn the failure,
                # then install only validated descendants. No revenge trade.
                self.adapt_after_loss(trade, reason)

        self.open_trades = remaining

    def cycle(self):
        print("\n[" + datetime.now().isoformat(timespec="seconds")
              + "] scanning...")
        self.settle_due_trades()

        markets = self.feed.fetch(MAX_MARKETS)
        print("[scan] markets:", len(markets))
        candidates = []
        for market in markets:
            proposal = self.evaluate(market)
            if proposal and self.risk.approve(proposal, self.bankroll):
                ok, reason = self.portfolio_risk.approve(
                    proposal.position_fraction,
                    self.positions,
                    self.daily_pnl,
                )
                if ok:
                    candidates.append(proposal)
                else:
                    print("[portfolio]", reason)

        candidates.sort(
            key=lambda p: abs(p.edge) * p.confidence,
            reverse=True,
        )
        print("[decision] passing all gates:", len(candidates))

        # One new paper position per cycle; portfolio limits remain authoritative.
        if candidates:
            self.paper_order(candidates[0])
        else:
            print("[decision] no trade")

    def run(self):
        print("Trading Company Agent 2.0 — PAPER MODE")
        while True:
            try:
                self.cycle()
            except KeyboardInterrupt:
                print("Stopped.")
                return
            except Exception as exc:
                print("[engine] recovered:", repr(exc))
            time.sleep(SCAN_SECONDS)


if __name__ == "__main__":
    TradingCompany().run()
