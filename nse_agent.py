"""Indian NSE multi-agent trading engine.

The default zero-cost mode uses Yahoo Finance research data and is PAPER-ONLY.
Live Zerodha execution requires an authorised Zerodha data provider as well as
the existing live-trading gates. No profitability is guaranteed.
"""
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from dataclasses import dataclass

from agent_learning import AgentLearningStore
from nse_market_data import NSEPublicFeed, NSEMarket
from zerodha_adapter import ZerodhaExecution, ZerodhaLocked

SCAN_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))
MIN_AGENTS = int(os.getenv("MIN_VALIDATED_AGENTS", "3"))
MAX_POSITION = float(os.getenv("MAX_POSITION_FRACTION", "0.06"))
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS_FRACTION", "0.03"))
MAX_DRAWDOWN = float(os.getenv("MAX_PORTFOLIO_DRAWDOWN_FRACTION", "0.10"))
MIN_CONF = float(os.getenv("NSE_MIN_CONFIDENCE", "0.58"))
MIN_SCORE = float(os.getenv("NSE_MIN_SCORE", "0.60"))
MAX_LIVE_DATA_AGE = float(os.getenv("MAX_LIVE_DATA_AGE_SECONDS", "10"))
PAPER_TAKE_PROFIT_MULTIPLE = float(os.getenv("PAPER_TAKE_PROFIT_MULTIPLE", "2.0"))
PAPER_MAX_HOLD_CYCLES = int(os.getenv("PAPER_MAX_HOLD_CYCLES", "12"))
PAPER_SLIPPAGE_BPS = float(os.getenv("PAPER_SLIPPAGE_BPS", "5"))
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
        self.cash = float(os.getenv("PAPER_STARTING_CAPITAL", "100000"))
        self.peak = self.cash
        self.daily_pnl = 0.0
        self.day = datetime.now().date().isoformat()
        self.open_positions = {}
        self.traded_today = set()
        self.realized_pnl = 0.0
        self.paper_cycle = 0

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
            "crypto_specialist-v1": 0.0,
            "x_social_research-v1": 0.0,
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
        score = sum(usable) / len(usable)
        conf = min(0.95, 0.55 + 0.40 * min(1, abs(score)))
        if abs(score) < MIN_SCORE or conf < MIN_CONF:
            return None
        direction = 1 if score > 0 else -1
        stop = max(0.003, min(0.02, 2.0 * f["vol"]))
        return Signal(
            market, direction, abs(score), conf, stop,
            "validated multi-agent NSE signal",
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
            self.daily_pnl = self.realized_pnl
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
                closed.append((market_id, reason, pnl, exit_price))
                del self.open_positions[market_id]
        equity = self._paper_equity(prices)
        self.daily_pnl = equity - self.cash
        self.peak = max(self.peak, equity)
        for market_id, reason, pnl, price in closed:
            print("[PAPER_EXIT]", market_id, reason, "pnl=%.2f" % pnl, "price=%.2f" % price)

    def paper_metrics(self, prices=None):
        prices = prices or {}
        equity = self._paper_equity(prices)
        unrealized = equity - self.cash - self.realized_pnl
        return {
            "cash": round(self.cash, 2),
            "equity": round(equity, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(unrealized, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "open_positions": len(self.open_positions),
            "peak_equity": round(self.peak, 2),
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
        max_notional = capital * MAX_POSITION
        qty = min(qty, max(1, int(max_notional / m.last_price)))
        if qty <= 0:
            return
        side = "BUY" if sig.direction > 0 else "SELL"
        if self.execution.enabled:
            price = m.last_price * (1 + 0.0005 * sig.direction)
            try:
                oid = self.execution.place_limit(
                    __import__("zerodha_adapter").OrderRequest(
                        m.tradingsymbol, m.exchange, side, qty, price,
                        os.getenv("ZERODHA_PRODUCT", "MIS"),
                    )
                )
                self.open_positions[m.market_id] = {
                    "order_id": oid, "side": side, "qty": qty
                }
                self.traded_today.add(m.market_id)
                print("[ZERODHA_ORDER]", oid, m.tradingsymbol, side, qty, price)
            except Exception as exc:
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

    def cycle(self):
        today = datetime.now().date().isoformat()
        if today != self.day:
            self.day = today
            self.daily_pnl = 0.0
            self.traded_today.clear()
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        if self.execution.enabled and (
            now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 15)
        ):
            try:
                self.execution.exit_all_intraday()
                self.open_positions.clear()
                print("[zerodha] intraday exit window reached; positions squared off")
            except Exception as exc:
                print("[zerodha exit] recovered", repr(exc))
            return
        print("\n[%s] NSE scanning..." % datetime.now().isoformat(timespec="seconds"))
        markets = self.feed.fetch(int(os.getenv("MAX_MARKETS_PER_SCAN", "100")))
        prices = {m.market_id: m.last_price for m in markets}
        self.paper_cycle += 1
        if not self.execution.enabled:
            self._mark_paper_positions(prices)

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
        if self.daily_pnl <= -self.cash * MAX_DAILY_LOSS or (
            1 - equity / max(self.peak, 1)
        ) >= MAX_DRAWDOWN:
            print("[risk] kill switch: daily loss/drawdown limit")
            return
        for m in markets[:int(os.getenv("NSE_RESEARCH_MARKETS_PER_CYCLE", "25"))]:
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
