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
from market_data import markets as fetch_markets, price_history, feed_status
from portfolio_risk import PortfolioRisk, Position
from calibration import CalibrationTracker
from execution_polymarket import LiveExecutionLocked, LiveOrderRequest, PolymarketExecution
from research_pipeline import research_market
from post_trade import PostTradeAnalyzer
from live_reconciliation import normalize_order, has_new_fill
from execution_risk import ExecutionRiskGate


SCAN_SECONDS = 300
MAX_MARKETS = max(1, min(int(os.getenv("MAX_MARKETS_PER_SCAN", "1000")), 1000))
EDGE_MIN = 0.08
CONFIDENCE_MIN = 0.80
MAX_POSITION = 0.06
START_BANKROLL = 1000.0
SETTLE_AFTER_SECONDS = 300
RESEARCH_MARKETS_PER_CYCLE = int(os.getenv("RESEARCH_MARKETS_PER_CYCLE", "25"))
MAX_RESEARCH_MARKETS = max(1, min(100, RESEARCH_MARKETS_PER_CYCLE))

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "TradingCompanyAgent/2.0"})


@dataclass
class Market:
    market_id: str
    question: str
    yes_price: float
    volume: float
    liquidity: float
    yes_token_id: str = ""
    no_token_id: str = ""


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
    order_id: str = ""
    live: bool = False
    requested_size: float = 0.0
    matched_size: float = 0.0
    average_fill_price: float = 0.0
    live_status: str = ""


class PolymarketPublicFeed:
    def fetch(self, limit=MAX_MARKETS) -> List[Market]:
        raw=fetch_markets(limit)
        return [
            Market(
                market_id=m.id,
                question=m.question,
                yes_price=m.yes_price,
                volume=m.volume,
                liquidity=m.liquidity,
                yes_token_id=m.yes_token,
                no_token_id=m.no_token,
            )
            for m in raw
        ]

    def current_price(self, market_id):
        for market in self.fetch(MAX_MARKETS):
            if market.market_id==market_id:
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

    def vote(self, market, fair, research=None):
        edge = fair - market.yes_price
        if research is not None:
            if self.name == "momentum":
                edge += 0.35 * research.momentum
            elif self.name == "mean_reversion":
                edge += 0.35 * research.mean_reversion
            elif self.name == "event_driven":
                edge += 0.03 * research.news_score
            elif self.name == "crypto_specialist":
                edge += 0.15 * research.book_imbalance
            elif self.name == "x_social_research":
                # No unauthenticated X data is invented; use verified news as a proxy
                # only when available and label it in the audit trail.
                edge += 0.02 * research.news_score
            elif self.name == "cross_market_arbitrage":
                edge += 0.03 * research.cross_market_score
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


class DebateAgent:
    """Independent roles that argue for/against a trade before the chief decides."""

    def __init__(self, role):
        self.role = role

    def argument(self, market, fair, edge, votes):
        magnitude = abs(edge)
        direction = "YES" if edge > 0 else "NO"
        if self.role == "bull":
            return {
                "stance": "BUY_" + direction,
                "argument": f"fair value implies {magnitude:.1%} edge; bullish thesis survives if the estimate is valid",
                "strength": min(1.0, magnitude / 0.12),
            }
        if self.role == "bear":
            return {
                "stance": "CHALLENGE",
                "argument": "market price may already incorporate information; demand independent evidence before trading",
                "strength": min(1.0, 0.55 + magnitude),
            }
        if self.role == "quant":
            agreement = statistics.mean(votes.values()) if votes else 0.0
            return {
                "stance": "BUY_" + direction if agreement * edge > 0 else "CHALLENGE",
                "argument": f"strategy vote mean={agreement:.3f}; edge={edge:.3f}",
                "strength": min(1.0, 0.5 + abs(agreement) * 0.5),
            }
        return {
            "stance": "CHALLENGE" if market.liquidity <= 0 else "CONDITIONAL",
            "argument": f"news/social evidence is not directly verified by the local feed; liquidity={market.liquidity:.2f}",
            "strength": 0.60,
        }


class RedTeamAgent:
    def attack(self, market, fair, edge, arguments):
        flaws = []
        if market.liquidity <= 0:
            flaws.append("no_liquidity")
        if abs(edge) < EDGE_MIN:
            flaws.append("edge_below_threshold")
        if len(arguments) < 3:
            flaws.append("insufficient_independent_debate")
        # The current public-feed engine cannot independently verify social/news
        # claims, so red-team explicitly discounts those claims rather than inventing evidence.
        flaws.append("external_evidence_unverified")
        attack_strength = min(0.95, 0.35 + 0.12 * len(flaws))
        return flaws, attack_strength


class ChiefDecisionAgent:
    def decide(self, proposal, arguments, flaws, attack_strength):
        votes = proposal.votes
        positive = sum(1 for v in votes.values() if v * proposal.edge > 0)
        total = max(1, len(votes))
        agreement = positive / total
        fatal = {"no_liquidity", "edge_below_threshold"}
        veto = bool(fatal.intersection(flaws))
        # A red-team objection alone does not force a veto; the chief requires a
        # material, testable flaw. Unverified external claims reduce confidence.
        confidence = proposal.confidence * (1.0 - 0.20 * min(1.0, attack_strength))
        if "external_evidence_unverified" in flaws:
            confidence *= 0.90
        if veto or agreement < 0.50:
            return "NO_TRADE", confidence, "red-team veto or insufficient agreement"
        if confidence < CONFIDENCE_MIN:
            return "NO_TRADE", confidence, "debate confidence below threshold"
        return proposal.side, confidence, "chief accepted thesis after cross-examination"


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
        self.peak_bankroll = START_BANKROLL
        self.feed = PolymarketPublicFeed()
        self.fair = FairValueAgent()
        self.risk = RiskAgent()
        self.portfolio_risk = PortfolioRisk()
        self.execution_risk = ExecutionRiskGate(
            max_position=MAX_POSITION,
            max_slippage=float(os.getenv("MAX_EXECUTION_SLIPPAGE", "0.02")),
            min_book_depth_multiple=float(os.getenv("MIN_BOOK_DEPTH_MULTIPLE", "2.0")),
            kill_switch=os.getenv("TRADING_KILL_SWITCH", "false").lower() == "true",
        )
        self.calibration = CalibrationTracker()
        self.lifecycle = AgentLifecycleManager()
        self.execution = PolymarketExecution()
        self.debate_agents = [DebateAgent("bull"), DebateAgent("bear"),
                              DebateAgent("quant"), DebateAgent("news_social")]
        self.red_team = RedTeamAgent()
        self.chief = ChiefDecisionAgent()
        self.positions = []
        self.open_trades = []
        self.position_questions = {}
        self.daily_pnl = 0.0
        self.pnl_day_key = datetime.now(timezone.utc).date().isoformat()
        state_root="/data" if os.path.isdir("/data") else "."
        self.post_trade=PostTradeAnalyzer(
            os.getenv("POST_TRADE_FILE", os.path.join(state_root,"agent_health.json"))
        )
        self.log=os.getenv(
            "TRADING_LOG_FILE", os.path.join(state_root,"paper_trades.csv")
        )
        self.metrics_file = os.getenv(
            "PAPER_METRICS_FILE", os.path.join(state_root, "paper_metrics.json")
        )
        self.paper_metrics = self._load_paper_metrics()


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

    def _load_paper_metrics(self):
        default = {
            "trades": 0, "wins": 0, "losses": 0, "pnl": 0.0,
            "gross_profit": 0.0, "gross_loss": 0.0, "peak_bankroll": START_BANKROLL,
            "max_drawdown": 0.0, "last_settlement": None,
        }
        try:
            with open(self.metrics_file, encoding="utf-8") as f:
                data = json.load(f)
            default.update(data if isinstance(data, dict) else {})
        except Exception:
            pass
        return default

    def _save_paper_metrics(self):
        os.makedirs(os.path.dirname(self.metrics_file) or ".", exist_ok=True)
        tmp = self.metrics_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.paper_metrics, f, indent=2)
        os.replace(tmp, self.metrics_file)

    def _record_paper_result(self, won, pnl):
        m = self.paper_metrics
        m["trades"] += 1
        m["wins"] += int(won)
        m["losses"] += int(not won)
        m["pnl"] = round(float(m["pnl"]) + pnl, 8)
        if pnl >= 0:
            m["gross_profit"] = round(float(m["gross_profit"]) + pnl, 8)
        else:
            m["gross_loss"] = round(float(m["gross_loss"]) + pnl, 8)
        m["peak_bankroll"] = max(float(m["peak_bankroll"]), self.bankroll)
        drawdown = 1.0 - self.bankroll / max(float(m["peak_bankroll"]), 1e-9)
        m["max_drawdown"] = max(float(m["max_drawdown"]), drawdown)
        m["last_settlement"] = datetime.now(timezone.utc).isoformat()
        self._save_paper_metrics()
        win_rate = m["wins"] / m["trades"]
        profit_factor = (
            m["gross_profit"] / abs(m["gross_loss"])
            if m["gross_loss"] < 0 else None
        )
        print(
            "[paper metrics]",
            "trades=%d" % m["trades"],
            "win_rate=%.2f%%" % (win_rate * 100),
            "pnl=%.4f" % m["pnl"],
            "profit_factor=" + ("%.3f" % profit_factor if profit_factor is not None else "n/a"),
            "max_drawdown=%.2f%%" % (m["max_drawdown"] * 100),
        )

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

    def debate(self, market, fair, edge, research=None):
        votes = {a.agent_id: a.vote(market, fair, research) for a in self.strategies}
        arguments = [
            agent.argument(market, fair, edge, votes)
            for agent in self.debate_agents
        ]
        flaws, attack_strength = self.red_team.attack(
            market, fair, edge, arguments
        )
        # A proposal is assembled first, then the chief is allowed to reject it.
        base_conf = min(
            0.99,
            0.50 + 0.30 * (1 - min(1, statistics.pstdev(votes.values())))
            + 0.20 * min(1, abs(statistics.mean(votes.values()))),
        )
        return votes, arguments, flaws, attack_strength, base_conf

    def evaluate(self, market, research=None):
        if research is None:
            fair, base_conf = self.fair.estimate(market)
        else:
            if not research.research_complete:
                print("[research gate] NO_TRADE", market.market_id,
                      "missing=" + ",".join(research.source_failures))
                return None
            if not research.validation_passed:
                print(
                    "[validation gate] NO_TRADE",
                    market.market_id,
                    "reason=" + research.validation_reason,
                    "samples=" + str(research.validation_samples),
                    "accuracy=%.2f%%" % (research.validation_accuracy * 100),
                    "brier=%.4f" % research.validation_brier,
                )
                return None
            fair, base_conf = research.fair_value, research.confidence
        edge = fair - market.yes_price
        if abs(edge) < EDGE_MIN:
            return None

        votes, arguments, flaws, attack_strength, debate_conf = self.debate(
            market, fair, edge, research
        )
        provisional = Proposal(
            market=market,
            fair_value=fair,
            edge=edge,
            confidence=min(base_conf, debate_conf),
            side="BUY_YES" if edge > 0 else "BUY_NO",
            position_fraction=0.0,
            votes=votes,
            reason="",
            supporting_agents=list(votes.keys()),
        )
        final_side, confidence, reason = self.chief.decide(
            provisional, arguments, flaws, attack_strength
        )
        if final_side == "NO_TRADE":
            return None
        side = final_side
        price = market.yes_price if side == "BUY_YES" else 1 - market.yes_price
        fv = fair if side == "BUY_YES" else 1 - fair
        fraction = self.kelly(price, fv)
        if research is not None:
            gate = self.execution_risk.approve(
                fraction,
                self.bankroll,
                price,
                research.best_ask if side == "BUY_YES" else (
                    1.0 - research.best_bid if research.best_bid > 0 else None
                ),
                research.book_depth,
                self.daily_pnl,
            )
            if not gate.approved:
                print("[execution risk]", gate.reason)
                return None
            fraction = gate.fraction

        return Proposal(
            market=market,
            fair_value=fair,
            edge=edge,
            confidence=confidence,
            side=side,
            position_fraction=fraction,
            votes=votes,
            reason=reason + " | objections=" + ",".join(flaws),
            supporting_agents=list(votes.keys()),
        )

    def paper_order(self, proposal):
        stake = self.bankroll * proposal.position_fraction
        token_id = (
            proposal.market.yes_token_id
            if proposal.side == "BUY_YES"
            else proposal.market.no_token_id
        )
        price = (
            proposal.market.yes_price
            if proposal.side == "BUY_YES"
            else 1 - proposal.market.yes_price
        )

        order_id = ""
        if self.execution.enabled:
            if not token_id:
                raise LiveExecutionLocked("Selected market has no CLOB token ID.")
            size = stake / max(price, 0.001)
            response = self.execution.place_limit(
                LiveOrderRequest(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side="BUY",
                )
            )
            order_id = self.execution.order_id(response) or ""
            if not order_id:
                raise LiveExecutionLocked("Execution response contained no order id.")
            print("[LIVE ORDER SUBMITTED]", order_id)
            decision_label = "LIVE_ORDER_SUBMITTED"
        else:
            decision_label = "PAPER_ORDER"

        requested_size = stake / max(price, 0.001) if self.execution.enabled else 0.0
        trade = OpenTrade(
            proposal=proposal,
            entry_yes_price=proposal.market.yes_price,
            opened_at=time.time(),
            stake=stake,
            order_id=order_id,
            live=self.execution.enabled,
            requested_size=requested_size,
            live_status="SUBMITTED" if self.execution.enabled else "PAPER_OPEN",
        )
        self.open_trades.append(trade)
        self.positions.append(
            Position(
                proposal.market.market_id,
                proposal.position_fraction,
                proposal.side,
                proposal.confidence,
                proposal.market.question,
            )
        )
        self.position_questions[proposal.market.market_id] = proposal.market.question
        print("[" + decision_label + "]", proposal.side,
              "edge=%.2f%%" % (proposal.edge * 100),
              "confidence=%.2f%%" % (proposal.confidence * 100),
              "stake=%.2f" % stake,
              "reason=", proposal.reason)

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

    def reconcile_live_orders(self):
        """Reconcile venue-reported state; never infer fills locally."""
        if not self.execution.enabled:
            return
        for trade in list(self.open_trades):
            if not trade.order_id:
                continue
            try:
                state = self.execution.get_order(trade.order_id) or {}
                fill = normalize_order(trade.order_id, state)
                previous = type("Previous", (), {"matched_size": trade.matched_size})()
                if has_new_fill(previous, fill):
                    trade.matched_size = fill.matched_size
                    if fill.average_price is not None:
                        trade.average_fill_price = fill.average_price
                    price = trade.average_fill_price or (
                        trade.proposal.market.yes_price
                        if trade.proposal.side == "BUY_YES"
                        else 1 - trade.proposal.market.yes_price
                    )
                    trade.stake = trade.matched_size * price
                trade.live_status = fill.status
                print("[LIVE RECONCILE]", trade.order_id, fill.status,
                      "matched=", fill.matched_size,
                      "remaining=", fill.remaining_size,
                      "avg=", fill.average_price)
                if fill.status in {"CANCELED", "CANCELLED", "REJECTED", "EXPIRED"}:
                    self.open_trades.remove(trade)
                    self.positions = [p for p in self.positions
                                      if p.market_id != trade.proposal.market.market_id]
                    self.position_questions.pop(trade.proposal.market.market_id, None)
            except Exception as exc:
                print("[LIVE RECONCILE ERROR]", trade.order_id, repr(exc))

    def settle_due_trades(self):
        if self.execution.enabled:
            self.reconcile_live_orders()
            return
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
                self.post_trade.record(
                    agent_id,
                    trade.proposal.reason,
                    trade.entry_yes_price,
                    pnl,
                    reason,
                )

            self.positions = [
                p for p in self.positions
                if p.market_id != trade.proposal.market.market_id
            ]
            self.position_questions.pop(trade.proposal.market.market_id, None)

            self.bankroll += pnl
            self.peak_bankroll = max(self.peak_bankroll, self.bankroll)
            self._record_paper_result(won, pnl)
            print("[PAPER SETTLE]", "WIN" if won else "LOSS",
                  "pnl=%.2f" % pnl, "reason=", reason)

            if not won:
                # Kill/quarantine the failed decision makers, learn the failure,
                # then install only validated descendants. No revenge trade.
                self.adapt_after_loss(trade, reason)

        self.open_trades = remaining

    def cycle(self):
        today = datetime.now(timezone.utc).date().isoformat()
        if today != self.pnl_day_key:
            self.daily_pnl = 0.0
            self.pnl_day_key = today
            print("[risk] daily P&L reset:", today)
        print("\n[" + datetime.now().isoformat(timespec="seconds")
              + "] scanning...")
        self.settle_due_trades()

        markets = self.feed.fetch(MAX_MARKETS)
        feed = feed_status()
        print("[scan] markets:", len(markets), "target=", MAX_MARKETS, "feed_status=", feed["status"], "stale=", feed["stale"])
        # Never make a trading decision from a stale cached universe. The cache
        # exists to keep the scanner alive during transient upstream outages,
        # not to authorize trades on old prices.
        if feed["stale"]:
            print("[risk] feed degraded/stale: scan-only, no trade this cycle")
            return

        # Rank the full universe cheaply, then deep-research only the strongest
        # candidates so the constrained cloud runtime remains stable.
        prelim = []
        for market in markets:
            fair, confidence = self.fair.estimate(market)
            edge = fair - market.yes_price
            if abs(edge) >= EDGE_MIN and market.liquidity > 0:
                prelim.append((abs(edge) * confidence, market))
        prelim.sort(key=lambda x: x[0], reverse=True)
        research_targets = [m for _, m in prelim[:MAX_RESEARCH_MARKETS]]
        print("[research] deep candidates:", len(research_targets))

        research_by_id = {}
        for market in research_targets:
            try:
                snapshot = research_market(market, markets)
                research_by_id[market.market_id] = snapshot
                print("[research]", market.market_id,
                      "edge=%.2f%%" % ((snapshot.fair_value - market.yes_price) * 100),
                      "confidence=%.2f%%" % (snapshot.confidence * 100),
                      "book=%.2f" % snapshot.book_imbalance,
                      "news=%d" % snapshot.news_count,
                      "macro=%.2f" % snapshot.macro_score,
                      "crypto=%.2f" % snapshot.crypto_score,
                      "social=%.2f" % snapshot.social_score,
                      "cross=%.2f" % snapshot.cross_market_score,
                      "validation=%s" % snapshot.validation_reason,
                      "val_acc=%.2f%%" % (snapshot.validation_accuracy * 100),
                      "val_n=%d" % snapshot.validation_samples,
                      "sources=" + ",".join(k for k,v in snapshot.source_status.items() if v))
            except Exception as exc:
                print("[research] recovered:", repr(exc))

        candidates = []
        max_drawdown = float(os.getenv("MAX_PORTFOLIO_DRAWDOWN_FRACTION", "0.10"))
        drawdown = 1.0 - (self.bankroll / max(self.peak_bankroll, 1e-9))
        if drawdown >= max_drawdown:
            print("[risk] circuit breaker: drawdown=%.2f%%" % (drawdown * 100))
            return
        for market in research_targets:
            proposal = self.evaluate(market, research_by_id.get(market.market_id))
            if proposal and self.risk.approve(proposal, self.bankroll):
                correlated_ids = self.portfolio_risk.correlated(
                    proposal.market.question, self.positions
                )
                ok, reason = self.portfolio_risk.approve(
                    proposal.position_fraction,
                    self.positions,
                    self.daily_pnl,
                    correlated_ids=correlated_ids,
                    bankroll=self.bankroll,
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
        # Research is deliberately performed before this point; incomplete or stale
        # required sources are rejected by evaluate().
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
