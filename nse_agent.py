"""Indian NSE multi-agent trading engine.

The default zero-cost mode uses Yahoo Finance research data and is PAPER-ONLY.
Live Zerodha execution requires an authorised Zerodha data provider as well as
the existing live-trading gates. No profitability is guaranteed.
"""
import json
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from dataclasses import dataclass

from agent_learning import AgentLearningStore
from nse_market_data import NSEPublicFeed, NSEMarket
from zerodha_adapter import ZerodhaExecution, ZerodhaLocked
from nse_debate import NSEPreTradeDebate
from nse_regime import classify as classify_regime
from trade_journal import TradeJournal
from zerodha_order_manager import ZerodhaOrderManager, OrderLifecycleError

SCAN_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))
MIN_AGENTS = int(os.getenv("MIN_VALIDATED_AGENTS", "3"))
MAX_POSITION = float(os.getenv("MAX_POSITION_FRACTION", "0.06"))
MAX_TOTAL_EXPOSURE = float(os.getenv("MAX_TOTAL_EXPOSURE_FRACTION", "0.30"))
MAX_DRAWDOWN = float(os.getenv("MAX_PORTFOLIO_DRAWDOWN_FRACTION", "0.10"))
MIN_CONF = float(os.getenv("NSE_MIN_CONFIDENCE", "0.58"))
MIN_SCORE = float(os.getenv("NSE_MIN_SCORE", "0.60"))
MAX_LIVE_DATA_AGE = float(os.getenv("MAX_LIVE_DATA_AGE_SECONDS", "10"))
PAPER_TAKE_PROFIT_MULTIPLE = float(os.getenv("PAPER_TAKE_PROFIT_MULTIPLE", "2.0"))
PAPER_MAX_HOLD_CYCLES = int(os.getenv("PAPER_MAX_HOLD_CYCLES", "12"))
PAPER_SLIPPAGE_BPS = float(os.getenv("PAPER_SLIPPAGE_BPS", "5"))
PAPER_STATE_FILE = os.getenv("PAPER_STATE_FILE", "data/nse_paper_state.json")
HORIZON = int(os.getenv("AGENT_LEARNING_HORIZON_SECONDS", "300"))


@dataclass
class Signal:
    market: NSEMarket
    direction: int
    score: float
    confidence: float
    stop_pct: float
    reason: str


class NSETradingCompany:
    def __init__(self):
        self.feed = NSEPublicFeed()
        self.execution = ZerodhaExecution()
        if self.execution.enabled and not self.feed.is_live_authorized_data:
            raise ZerodhaLocked(
                "Live Zerodha execution is blocked when NSE_MARKET_DATA_PROVIDER "
                "is not 'zerodha'. The free Yahoo provider is research/paper-only."
            )
        self.learning = AgentLearningStore(horizon_seconds=HORIZON)
        self.debate = NSEPreTradeDebate(
            min_agreement=float(os.getenv("DEBATE_MIN_AGREEMENT", "0.60")),
            max_conflict=float(os.getenv("DEBATE_MAX_CONFLICT", "0.45")),
        )
        self.journal = TradeJournal()
        self.order_manager = ZerodhaOrderManager(self.execution, self.journal)
        self.cash = float(os.getenv("PAPER_STARTING_CAPITAL", "100000"))
        self.peak = self.cash
        self.daily_pnl = 0.0
        self.day = datetime.now().date().isoformat()
        self.open_positions = {}
        self.traded_today = set()
        self.realized_pnl = 0.0
        self.daily_realized_pnl = 0.0
        self.paper_cycle = 0
        self._load_paper_state()

    def _load_paper_state(self):
        try:
            if not os.path.exists(PAPER_STATE_FILE):
                return
            with open(PAPER_STATE_FILE, encoding="utf-8") as f:
                state = json.load(f)
            self.cash = float(state.get("cash", self.cash))
            self.peak = float(state.get("peak", self.peak))
            self.realized_pnl = float(state.get("realized_pnl", 0.0))
            self.daily_realized_pnl = float(state.get("daily_realized_pnl", 0.0))
            self.daily_pnl = float(state.get("daily_pnl", 0.0))
            self.day = state.get("day", self.day)
            self.open_positions = state.get("open_positions", {})
            self.traded_today = set(state.get("traded_today", []))
            self.paper_cycle = int(state.get("paper_cycle", 0))
        except Exception as exc:
            print("[paper state recovered]", repr(exc))

    def _save_paper_state(self):
        try:
            parent = os.path.dirname(PAPER_STATE_FILE)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = PAPER_STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({
                    "cash": self.cash,
                    "peak": self.peak,
                    "realized_pnl": self.realized_pnl,
                    "daily_realized_pnl": self.daily_realized_pnl,
                    "daily_pnl": self.daily_pnl,
                    "day": self.day,
                    "open_positions": self.open_positions,
                    "traded_today": sorted(self.traded_today),
                    "paper_cycle": self.paper_cycle,
                    "learning": self.learning.summary(),
                    "risk": self._paper_risk_snapshot(),
                    "updated_at": datetime.now().isoformat(),
                }, f, indent=2)
            os.replace(tmp, PAPER_STATE_FILE)
        except Exception as exc:
            print("[paper state save recovered]", repr(exc))

    @staticmethod
    def _returns(prices):
        return [
            (prices[i] / prices[i - 1]) - 1.0
            for i in range(1, len(prices))
            if prices[i - 1] > 0
        ]

    def features(self, market):
        rows = self.feed.history(
            market, days=10, interval=os.getenv("NSE_INTERVAL", "5m")
        )
        closes = [float(r["close"]) for r in rows if r.get("close")]
        vols = [float(r.get("volume", 0)) for r in rows]
        if len(closes) < 30:
            return None
        rs = self._returns(closes[-120:])
        if len(rs) < 20:
            return None
        r5 = closes[-1] / closes[-6] - 1
        r20 = closes[-1] / closes[-21] - 1
        mean = sum(closes[-30:]) / 30
        reversion = (closes[-1] / mean) - 1
        avg_r = sum(rs[-30:]) / min(30, len(rs))
        vol = (sum((r - avg_r) ** 2 for r in rs[-30:]) / min(30, len(rs))) ** 0.5
        recent_vol = sum(vols[-10:]) / max(1, sum(vols[-40:-10]) / 30)
        breakout = (
            closes[-1] / max(closes[-21:-1]) - 1 if len(closes) >= 22 else 0
        )
        return {
            "r5": r5,
            "r20": r20,
            "reversion": reversion,
            "vol": max(vol, 0.0005),
            "volume_ratio": recent_vol,
            "breakout": breakout,
            "price": closes[-1],
        }

    def agent_votes(self, f):
        votes = {
            "momentum-v1": 0.55 * f["r5"] + 0.45 * f["r20"],
            "mean_reversion-v1": -f["reversion"],
            "event_driven-v1": 0.40 * f["breakout"] + 0.20 * (f["volume_ratio"] - 1),
            "cross_market_arbitrage-v1": 0.50 * f["r20"] + 0.20 * (f["volume_ratio"] - 1),
        }
        return {
            k: max(-1.0, min(1.0, v / max(f["vol"] * 4, 0.002)))
            for k, v in votes.items()
        }

    def learn(self, market, f, votes):
        self.learning.record_observation(market.market_id, f["price"], save=False)
        conf = min(
            0.95,
            0.55 + 0.35 * min(1.0, abs(sum(votes.values())) / max(1, len(votes))),
        )
        edge = sum(votes.values()) / max(1, len(votes)) * f["vol"]
        self.learning.record_forecast(
            market.market_id,
            market.question,
            f["price"],
            votes,
            conf,
            edge,
            now=time.time(),
        )

    def signal(self, market, f, votes):
        qualified, _ = self.learning.qualified_agents(list(votes.keys()))
        q = set(qualified)
        usable = [v for a, v in votes.items() if a in q and abs(v) > 0.05]
        if len(q) < MIN_AGENTS or len(usable) < MIN_AGENTS:
            return None
        regime = classify_regime(f)
        debate = self.debate.run(f, votes, qualified)
        self.journal.record(
            "DEBATE",
            symbol=market.tradingsymbol,
            regime=regime.name,
            decision=debate.decision,
            agreement=debate.agreement,
            conflict=debate.conflict,
            score=debate.score,
            challenges=debate.challenges,
        )
        if debate.decision == "NO_TRADE":
            return None
        if regime.direction and debate.direction != regime.direction and regime.confidence >= 0.70:
            self.journal.record("REGIME_BLOCK", symbol=market.tradingsymbol, regime=regime.name)
            return None
        if debate.score < MIN_SCORE or debate.confidence < MIN_CONF:
            return None
        stop = max(0.003, min(0.02, 2.0 * f["vol"]))
        return Signal(
            market, debate.direction, debate.score, debate.confidence, stop,
            "debate-approved: " + debate.rationale,
        )

    def _paper_fill_price(self, price, side):
        slip = PAPER_SLIPPAGE_BPS / 10000.0
        return price * (1 + slip if side == "BUY" else 1 - slip)

    def _paper_equity(self, prices):
        equity = self.cash + self.realized_pnl
        for position in self.open_positions.values():
            current = prices.get(position["market_id"], position["entry"])
            signed = 1 if position["side"] == "BUY" else -1
            equity += signed * (current - position["entry"]) * position["qty"]
        return equity

    def _mark_paper_positions(self, prices):
        if not self.open_positions:
            self.daily_pnl = self.daily_realized_pnl
            return
        closed = []
        for market_id, position in list(self.open_positions.items()):
            current = prices.get(market_id)
            if current is None or current <= 0:
                continue
            signed = 1 if position["side"] == "BUY" else -1
            move = signed * (current - position["entry"]) / position["entry"]
            stop = position["stop_pct"]
            reason = None
            if move <= -stop:
                reason = "stop"
            elif move >= stop * PAPER_TAKE_PROFIT_MULTIPLE:
                reason = "take_profit"
            elif self.paper_cycle - position["entry_cycle"] >= PAPER_MAX_HOLD_CYCLES:
                reason = "time_exit"
            if reason:
                exit_price = self._paper_fill_price(current, "SELL" if position["side"] == "BUY" else "BUY")
                pnl = signed * (exit_price - position["entry"]) * position["qty"]
                self.realized_pnl += pnl
                self.daily_realized_pnl += pnl
                closed.append((market_id, reason, pnl, exit_price))
                del self.open_positions[market_id]
        equity = self._paper_equity(prices)
        self.daily_pnl = self.daily_realized_pnl + (equity - self.cash - self.realized_pnl)
        self.peak = max(self.peak, equity)
        for market_id, reason, pnl, price in closed:
            print("[PAPER_EXIT]", market_id, reason, "pnl=%.2f" % pnl, "price=%.2f" % price)

    def _close_all_paper_positions(self, prices, reason="session_end"):
        """Close all paper positions at the supplied session-end prices."""
        closed = []
        for market_id, position in list(self.open_positions.items()):
            current = prices.get(market_id)
            if current is None or current <= 0:
                continue
            signed = 1 if position["side"] == "BUY" else -1
            exit_side = "SELL" if position["side"] == "BUY" else "BUY"
            exit_price = self._paper_fill_price(current, exit_side)
            pnl = signed * (exit_price - position["entry"]) * position["qty"]
            self.realized_pnl += pnl
            self.daily_realized_pnl += pnl
            closed.append((market_id, reason, pnl, exit_price))
            del self.open_positions[market_id]
        if closed:
            equity = self._paper_equity(prices)
            self.daily_pnl = self.daily_realized_pnl
            self.peak = max(self.peak, equity)
            for market_id, why, pnl, price in closed:
                print("[PAPER_SESSION_EXIT]", market_id, why,
                      "pnl=%.2f" % pnl, "price=%.2f" % price)
        return len(closed)

    def _paper_risk_snapshot(self, prices=None):
        prices = prices or {}
        gross_notional = 0.0
        for position in self.open_positions.values():
            current = prices.get(position.get("market_id"), position.get("entry", 0.0))
            gross_notional += abs(float(current or 0.0) * float(position.get("qty", 0)))
        equity = self._paper_equity(prices)
        return {
            "gross_notional": round(gross_notional, 2),
            "gross_exposure_fraction": round(gross_notional / max(equity, 1.0), 6),
            "open_positions": len(self.open_positions),
            "drawdown_fraction": round(max(0.0, 1.0 - equity / max(self.peak, 1.0)), 6),
            "daily_loss_fraction": round(max(0.0, -self.daily_pnl) / max(self.cash, 1.0), 6),
        }

    def paper_metrics(self, prices=None):
        prices = prices or {}
        equity = self._paper_equity(prices)
        unrealized = equity - self.cash - self.realized_pnl
        risk = self._paper_risk_snapshot(prices)
        return {
            "cash": round(self.cash, 2),
            "equity": round(equity, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "open_positions": len(self.open_positions),
            "peak_equity": round(self.peak, 2),
            "drawdown_fraction": risk["drawdown_fraction"],
            "gross_notional": risk["gross_notional"],
            "gross_exposure_fraction": risk["gross_exposure_fraction"],
        }

    def paper_or_live(self, sig):
        m = sig.market
        capital = self.execution.funds_available() if self.execution.enabled else self.cash
        if capital is None or capital <= 0:
            print("[risk] no available Zerodha equity margin; no order")
            return
        risk_cap = capital * MAX_POSITION
        risk_per_share = max(m.last_price * sig.stop_pct, 0.05)
        qty = max(1, int(risk_cap / risk_per_share))

        # Enforce a portfolio-wide exposure ceiling in addition to the
        # per-position cap.
        existing_notional = 0.0
        for position in self.open_positions.values():
            entry = float(position.get("entry", 0.0) or 0.0)
            existing_notional += abs(entry * int(position.get("qty", 0) or 0))
        remaining_notional = max(0.0, capital * MAX_TOTAL_EXPOSURE - existing_notional)
        if remaining_notional < m.last_price:
            print("[risk] total exposure cap reached; no order")
            return

        max_notional = min(capital * MAX_POSITION, remaining_notional)
        qty = min(qty, int(max_notional / m.last_price))
        if qty <= 0:
            return
        side = "BUY" if sig.direction > 0 else "SELL"
        self.journal.record(
            "ORDER_INTENT",
            symbol=m.tradingsymbol,
            side=side,
            quantity=qty,
            reference_price=m.last_price,
            score=sig.score,
            confidence=sig.confidence,
            reason=sig.reason,
        )
        if self.execution.enabled:
            price = m.last_price * (1 + 0.0005 * sig.direction)
            try:
                intent_id = f"nse-{self.paper_cycle}-{m.market_id}-{side}-{qty}"
                request = __import__("zerodha_adapter").OrderRequest(
                    m.tradingsymbol, m.exchange, side, qty, price,
                    os.getenv("ZERODHA_PRODUCT", "MIS"), intent_id,
                )
                fill = self.order_manager.submit(request, intent_id)
                filled = int(fill["filled_quantity"])
                avg_price = float(fill["average_price"])
                if filled <= 0 or avg_price <= 0:
                    raise OrderLifecycleError("broker returned no confirmed fill")
                self.open_positions[m.market_id] = {
                    "market_id": m.market_id,
                    "order_id": fill["order_id"],
                    "side": side,
                    "qty": filled,
                    "entry": avg_price,
                    "stop_pct": sig.stop_pct,
                    "entry_cycle": self.paper_cycle,
                }
                self.traded_today.add(m.market_id)
                print("[ZERODHA_FILL]", fill)
            except Exception as exc:
                self.journal.record("ORDER_FAILURE", symbol=m.tradingsymbol, error=repr(exc))
                print("[zerodha execution blocked]", repr(exc))
        else:
            entry = self._paper_fill_price(m.last_price, side)
            self.open_positions[m.market_id] = {
                "market_id": m.market_id,
                "side": side,
                "qty": qty,
                "entry": entry,
                "stop_pct": sig.stop_pct,
                "entry_cycle": self.paper_cycle,
            }
            self.traded_today.add(m.market_id)
            print(
                "[PAPER_ORDER]", m.tradingsymbol, side, qty, m.last_price,
                "score=%.3f" % sig.score, "confidence=%.2f" % sig.confidence,
            )

    def _reconcile_live_state(self):
        """Fail closed if broker positions disagree with the engine's state."""
        if not self.execution.enabled:
            return True
        broker_positions = self.execution.positions().get("day", [])
        broker = {}
        for p in broker_positions:
            if p.get("exchange") != "NSE":
                continue
            qty = int(p.get("quantity", 0) or 0)
            if qty:
                broker[p.get("tradingsymbol")] = qty
        local = {}
        for p in self.open_positions.values():
            qty = int(p.get("qty", 0) or 0)
            if qty:
                signed = qty if p.get("side") == "BUY" else -qty
                local[p.get("market_id")] = local.get(p.get("market_id"), 0) + signed
        if set(local) != set(broker):
            self.journal.record("RECONCILIATION_FAILURE", local=local, broker=broker)
            return False
        for symbol, qty in broker.items():
            local_qty = 0
            for p in self.open_positions.values():
                if p.get("market_id") == symbol:
                    local_qty += int(p.get("qty", 0) or 0) * (1 if p.get("side") == "BUY" else -1)
            if local_qty != qty:
                self.journal.record("RECONCILIATION_FAILURE", symbol=symbol, local=local_qty, broker=qty)
                return False
        return True

    def cycle(self):
        if os.getenv("LIVE_KILL_SWITCH", "false").lower() == "true":
            self.journal.record("KILL_SWITCH", reason="LIVE_KILL_SWITCH")
            print("[risk] live kill switch active; no cycle executed")
            return
        if self.execution.enabled and not self._reconcile_live_state():
            raise ZerodhaLocked("Broker/local position reconciliation failed; new trading is blocked.")
        today = datetime.now().date().isoformat()
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        session_end = (
            now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 15)
        )

        if session_end and not self.execution.enabled and not self.open_positions:
            print("[paper] NSE session closed; no after-hours paper cycle.")
            self._save_paper_state()
            return

        if self.execution.enabled and session_end:
            try:
                self.execution.exit_all_intraday()
                self.open_positions.clear()
                print("[zerodha] intraday exit window reached; positions squared off")
            except Exception as exc:
                print("[zerodha exit] recovered", repr(exc))
            return

        print("\n[%s] NSE scanning..." % datetime.now().isoformat(timespec="seconds"))
        markets = self.feed.fetch(int(os.getenv("MAX_MARKETS_PER_SCAN", "1000")))
        print("[nse] market universe scanned=", len(markets))
        prices = {m.market_id: m.last_price for m in markets}
        if not self.execution.enabled:
            self.feed.prefetch_history(markets, days=10, interval=os.getenv("NSE_INTERVAL", "5m"))

        if today != self.day:
            if not self.execution.enabled and self.open_positions:
                self._close_all_paper_positions(prices, "new_session")
            self.day = today
            self.daily_pnl = 0.0
            self.daily_realized_pnl = 0.0
            self.traded_today.clear()

        self.paper_cycle += 1
        if not self.execution.enabled:
            self._mark_paper_positions(prices)

        if session_end and not self.execution.enabled:
            closed = self._close_all_paper_positions(prices, "session_end")
            print("[paper] session close; positions_closed=", closed)
            self._save_paper_state()
            print("[paper]", self.paper_metrics(prices))
            return

        if self.execution.enabled:
            if not self.feed.is_live_authorized_data:
                raise ZerodhaLocked("Live execution requires an authorised market-data provider.")
            stale = [m.tradingsymbol for m in markets if self.feed.freshness_seconds(m) > MAX_LIVE_DATA_AGE]
            if stale:
                raise ZerodhaLocked(f"Live execution blocked: market data is stale for {len(stale)} symbols.")
        resolved = self.learning.resolve(prices.get)
        qualified, _ = self.learning.qualified_agents(
            [
                "momentum-v1",
                "mean_reversion-v1",
                "event_driven-v1",
                "cross_market_arbitrage-v1",
            ]
        )
        print(
            "[learning] resolved=", resolved,
            "history=", len(self.learning.data["history"]),
            "observations=", self.learning.observation_count(),
            "qualified=", len(qualified),
        )
        equity = self._paper_equity(prices) if not self.execution.enabled else self.cash
        if (1 - equity / max(self.peak, 1)) >= MAX_DRAWDOWN:
            print("[risk] kill switch: portfolio drawdown limit")
            return
        for m in markets[:int(os.getenv("NSE_RESEARCH_MARKETS_PER_CYCLE", "1000"))]:
            try:
                f = self.features(m)
                if not f:
                    continue
                votes = self.agent_votes(f)
                self.learn(m, f, votes)
                sig = self.signal(m, f, votes)
                if (
                    sig
                    and m.market_id not in self.traded_today
                    and m.market_id not in self.open_positions
                ):
                    self.paper_or_live(sig)
            except Exception as exc:
                print("[nse cycle recovered]", m.tradingsymbol, repr(exc))
        self.learning._save()
        if not self.execution.enabled:
            self._save_paper_state()
        if not self.execution.enabled:
            print("[paper]", self.paper_metrics(prices))
        print(
            "[nse] provider=", self.feed.provider,
            "data_label=", self.feed.data_label,
            "free_data=", self.feed.is_free_data,
            "markets=", len(markets),
            "qualified=", len(qualified),
            "live=", self.execution.enabled,
        )

    def run(self):
        while True:
            try:
                self.cycle()
            except Exception as exc:
                print("[nse supervisor] recovered", repr(exc))
            time.sleep(SCAN_SECONDS)


if __name__ == "__main__":
    NSETradingCompany().run()
