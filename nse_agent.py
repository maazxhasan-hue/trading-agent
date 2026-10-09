"""Indian NSE multi-agent trading engine.

The default zero-cost mode uses Yahoo Finance research data and is PAPER-ONLY.
Live Zerodha execution requires an authorised Zerodha data provider as well as
the existing live-trading gates. No profitability is guaranteed.
"""
import json
import hashlib
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from dataclasses import dataclass

from agent_learning import AgentLearningStore
from nse_market_data import NSEPublicFeed, NSEMarket
try:
    from mcx_market_data import MCXPublicFeed
except ImportError:
    MCXPublicFeed = None
from zerodha_adapter import ZerodhaExecution, ZerodhaLocked
from angelone_adapter import AngelOneExecution, AngelOneLocked
from angelone_market_data import AngelOneNSEFeed
try:
    from angelone_mcx_market_data import AngelOneMCXFeed
except ImportError:
    AngelOneMCXFeed = None
from nse_debate import NSEPreTradeDebate
from nse_regime import classify as classify_regime
from trade_journal import TradeJournal
from mcx_tournament import TournamentLedger
from mcx_paper_portfolios import MCXPaperPortfolioBook
from mcx_paper_tournament import MCXPaperTournamentBridge
from mcx_gen_evolution import MCXGenEvolutionController
from trading_city import TradingCity
from zerodha_order_manager import ZerodhaOrderManager, OrderLifecycleError
from angelone_order_manager import AngelOneOrderManager
import hq_events

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
PAPER_STATE_FILE = os.getenv("PAPER_STATE_FILE", "data/mcx_paper_state.json" if os.getenv("TRADING_BACKEND","").lower()=="mcx" else "data/nse_paper_state.json")
HORIZON = int(os.getenv("AGENT_LEARNING_HORIZON_SECONDS", "300"))


@dataclass
class Signal:
    market: NSEMarket
    direction: int
    score: float
    confidence: float
    stop_pct: float
    reason: str
    features: dict | None = None
    agent_votes: dict | None = None


class NSETradingCompany:
    def __init__(self):
        backend = os.getenv("TRADING_BACKEND", "zerodha_nse").lower()
        self.backend = backend
        self.city = TradingCity(os.getenv("TRADING_CITY_STATE_FILE", "data/trading_city_state.json"))
        for agent_id, role in (
            ("research", "market_research"), ("momentum", "momentum"),
            ("mean_reversion", "mean_reversion"), ("event_driven", "event_research"),
            ("redteam", "adversarial_review"), ("risk", "risk_gate"),
            ("chief", "orchestration"),
        ):
            self.city.register_agent(agent_id, role, "IDLE")
        if backend == "mcx":
            self.feed = MCXPublicFeed()
            self.execution = ZerodhaExecution()
        elif self.backend == "angelone_mcx":
            if AngelOneMCXFeed is None:
                raise RuntimeError("Angel One MCX feed is unavailable.")
            self.feed = AngelOneMCXFeed()
            self.execution = AngelOneExecution()
        elif self.backend == "angelone_nse":
            self.feed = AngelOneNSEFeed()
            self.execution = AngelOneExecution()
        else:
            self.feed = NSEPublicFeed()
            self.execution = ZerodhaExecution()
        if self.execution.enabled and not self.feed.is_live_authorized_data:
            raise (AngelOneLocked if backend == "angelone_nse" else ZerodhaLocked)(
                "Live execution requires an authorised market-data provider."
            )
        self.learning = AgentLearningStore(horizon_seconds=HORIZON)
        self._feature_candles = {}
        self._hq_candle_ids = set()
        self.debate = NSEPreTradeDebate(
            min_agreement=float(os.getenv("DEBATE_MIN_AGREEMENT", "0.60")),
            max_conflict=float(os.getenv("DEBATE_MAX_CONFLICT", "0.45")),
        )
        self.journal = TradeJournal()
        if backend in {"angelone_nse", "angelone_mcx"}:
            self.order_manager = AngelOneOrderManager(self.execution, self.journal)
        else:
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
        self.total_paper_trades = 0
        # Paper-only evolutionary lifecycle. Losing paper trades kill the
        # current generation; replacements inherit accumulated knowledge.
        self.paper_generation = 1
        self.paper_agent_alive = True
        self.paper_agent_knowledge = []
        self._load_paper_state()
        self.tournament = None
        self.gen_evolution = None
        if self.backend in {"mcx", "angelone_mcx"}:
            self.tournament = TournamentLedger(
                path=os.getenv("MCX_TOURNAMENT_STATE_FILE", "data/mcx_tournament.json"),
                target_pnl=float(os.getenv("PAPER_TOURNAMENT_TARGET_PNL", "1000")),
                window_seconds=int(os.getenv("PAPER_TOURNAMENT_WINDOW_SECONDS", "3600")),
                min_trades=int(os.getenv("PAPER_TOURNAMENT_MIN_TRADES", "3")),
                max_drawdown_fraction=float(os.getenv("PAPER_TOURNAMENT_MAX_DRAWDOWN", "0.10")),
            )
            self.tournament.ensure_generation(self.paper_generation,
                parent_generation=self.paper_generation - 1 if self.paper_generation > 1 else None)
            self.mcx_paper_bridge = None
            if not self.execution.enabled:
                self.mcx_portfolios = MCXPaperPortfolioBook(
                    path=os.getenv("MCX_GEN_PORTFOLIOS_FILE", "data/mcx_gen_portfolios.json"),
                    starting_cash=float(os.getenv("MCX_GEN_STARTING_CAPITAL", "100")),
                    max_position_fraction=MAX_POSITION,
                    max_total_exposure_fraction=MAX_TOTAL_EXPOSURE,
                    slippage_bps=float(os.getenv("PAPER_SLIPPAGE_BPS", "5")),
                    fee_bps=float(os.getenv("PAPER_FEE_BPS", "2")),
                    max_hold_cycles=PAPER_MAX_HOLD_CYCLES,
                )
                self.mcx_paper_bridge = MCXPaperTournamentBridge(
                    self.tournament,
                    self.mcx_portfolios,
                    population_size=int(os.getenv("MCX_GEN_POPULATION_SIZE", "5")),
                    max_quote_age_seconds=MAX_LIVE_DATA_AGE,
                    manage_replacements=False,
                )
                self.gen_evolution = MCXGenEvolutionController(
                    self.tournament,
                    state_path=os.getenv("MCX_GEN_EVOLUTION_STATE_FILE", "data/mcx_gen_evolution.json"),
                    population_size=int(os.getenv("MCX_GEN_POPULATION_SIZE", "5")),
                    tournament_seconds=int(os.getenv("MCX_GEN_TOURNAMENT_SECONDS", "10800")),
                    target_hourly_net_pnl=float(os.getenv("PAPER_TOURNAMENT_TARGET_PNL", "1000")),
                    portfolios=self.mcx_portfolios,
                )

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
            self.total_paper_trades = int(state.get("total_paper_trades", 0))
            self.paper_generation = max(1, int(state.get("paper_generation", 1)))
            self.paper_agent_alive = bool(state.get("paper_agent_alive", True))
            self.paper_agent_knowledge = list(state.get("paper_agent_knowledge", []))[-1000:]
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
                    "total_paper_trades": self.total_paper_trades,
                    "paper_generation": self.paper_generation,
                    "paper_agent_alive": self.paper_agent_alive,
                    "paper_agent_knowledge": self.paper_agent_knowledge[-1000:],
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
        interval = os.getenv("MARKET_INTERVAL", os.getenv("NSE_INTERVAL", "5m"))
        rows = self.feed.history(market, days=2, interval=interval)
        self._feature_candles[market.market_id] = rows[-120:]
        closes = [float(r["close"]) for r in rows if r.get("close")]
        vols = [float(r.get("volume", 0)) for r in rows]
        if len(closes) < 30:
            return None
        rs = self._returns(closes[-120:])
        if len(rs) < 20:
            return None
        r3 = closes[-1] / closes[-4] - 1
        r5 = closes[-1] / closes[-6] - 1
        r10 = closes[-1] / closes[-11] - 1
        r20 = closes[-1] / closes[-21] - 1
        mean = sum(closes[-30:]) / 30
        reversion = (closes[-1] / mean) - 1
        ema_fast = sum(closes[-10:]) / 10
        ema_slow = sum(closes[-30:]) / 30
        trend_gap = (ema_fast / max(ema_slow, 1e-12)) - 1
        avg_r = sum(rs[-30:]) / min(30, len(rs))
        vol = (sum((r - avg_r) ** 2 for r in rs[-30:]) / min(30, len(rs))) ** 0.5
        recent_vol = sum(vols[-10:]) / max(1, sum(vols[-40:-10]) / 30)
        ranges = [
            max(float(r.get("high", 0)) - float(r.get("low", 0)), 0.0)
            for r in rows
        ]
        range_now = sum(ranges[-5:]) / max(1, len(ranges[-5:]))
        range_base = sum(ranges[-30:-5]) / max(1, len(ranges[-30:-5]))
        range_ratio = range_now / max(range_base, closes[-1] * 0.0005)
        gains = [max(x, 0.0) for x in rs[-14:]]
        losses = [max(-x, 0.0) for x in rs[-14:]]
        avg_gain = sum(gains) / max(1, len(gains))
        avg_loss = sum(losses) / max(1, len(losses))
        rs_value = avg_gain / max(avg_loss, 1e-12)
        rsi = 100.0 - (100.0 / (1.0 + rs_value))
        breakout = closes[-1] / max(closes[-21:-1]) - 1 if len(closes) >= 22 else 0
        breakdown = min(0.0, closes[-1] / min(closes[-21:-1]) - 1) if len(closes) >= 22 else 0
        return {
            "r3": r3,
            "r5": r5,
            "r10": r10,
            "r20": r20,
            "reversion": reversion,
            "trend_gap": trend_gap,
            "vol": max(vol, 0.0005),
            "volume_ratio": recent_vol,
            "range_ratio": range_ratio,
            "rsi": rsi,
            "breakout": breakout,
            "breakdown": breakdown,
            "price": closes[-1],
        }

    def agent_votes(self, f, market):
        # v3 uses bounded, regime-aware signals and deliberately avoids
        # overconfident probabilities. The validation target is out-of-sample
        # directional quality, not maximizing the raw signal magnitude.
        trend_score = (
            0.30 * f["r3"] + 0.30 * f["r10"] + 0.20 * f["r20"] + 0.20 * f["trend_gap"]
        )
        momentum = trend_score * (1.0 + 0.25 * min(2.0, f["volume_ratio"]))

        stretch = abs(f["reversion"]) / max(f["vol"], 0.0005)
        rsi_extreme = (f["rsi"] - 50.0) / 50.0
        mean_reversion = (
            -f["reversion"]
            * min(1.75, 0.75 + 0.25 * stretch)
            * (1.0 - min(0.40, abs(f["trend_gap"]) / max(f["vol"] * 8.0, 0.004)))
            * (1.0 + 0.35 * abs(rsi_extreme))
        )

        breakout_signal = f["breakout"] if f["breakout"] > 0 else f["breakdown"]
        event = (
            0.55 * breakout_signal
            + 0.25 * (f["volume_ratio"] - 1.0) * (1 if breakout_signal >= 0 else -1)
            + 0.20 * (f["range_ratio"] - 1.0) * (1 if f["r3"] >= 0 else -1)
        )

        relative_value = (
            0.45 * (f["r3"] - 0.25 * f["r20"])
            + 0.30 * (f["r10"] - f["r20"])
            + 0.25 * f["trend_gap"]
        )

        # MCX commodity specialist: deliberately different evidence from the
        # generic technical agents. It emphasizes contract/commodity regime,
        # volatility, liquidity, and trend-vs-stretch behavior. The signal is
        # bounded and remains only one vote inside the independent debate.
        specialist = 0.0
        symbol = str(getattr(market, "tradingsymbol", "")).upper()
        if self.backend in {"mcx", "angelone_mcx"}:
            commodity = (
                "GOLD" if "GOLD" in symbol else
                "SILVER" if "SILVER" in symbol else
                "CRUDE" if "CRUDE" in symbol else
                "NATURALGAS" if "NATURALGAS" in symbol else
                "COPPER" if "COPPER" in symbol else                "ZINC" if "ZINC" in symbol else
                "OTHER"
            )
            # Precious metals favor trend persistence; energy favors breakout
            # and volatility confirmation; industrial metals favor relative
            # momentum plus volume confirmation.
            if commodity in {"GOLD", "SILVER"}:
                specialist = (
                    0.40 * f["r20"] + 0.30 * f["trend_gap"]
                    + 0.20 * f["r10"] + 0.10 * (f["volume_ratio"] - 1.0)
                )
            elif commodity in {"CRUDE", "NATURALGAS"}:
                specialist = (
                    0.30 * f["breakout"] + 0.25 * f["r10"]
                    + 0.20 * f["range_ratio"] * (1 if f["r5"] >= 0 else -1)
                    + 0.25 * (f["volume_ratio"] - 1.0)
                )
            else:
                specialist = (
                    0.35 * f["r10"] + 0.25 * f["r20"]
                    + 0.20 * f["trend_gap"]
                    + 0.20 * (f["volume_ratio"] - 1.0)
                )

            # Avoid chasing unusually stretched commodity moves.
            stretch_penalty = min(
                0.50,
                max(0.0, abs(f["reversion"]) / max(f["vol"], 0.0005) - 2.0) * 0.08,
            )
            specialist -= (1 if specialist >= 0 else -1) * stretch_penalty

        votes = {
            "momentum-v3": momentum,
            "mean_reversion-v3": mean_reversion,
            "event_driven-v3": event,
            "mcx_commodity_specialist-v3": specialist,
            "cross_market_arbitrage-v3": relative_value,
        }
        return {
            k: max(-1.0, min(1.0, v / max(f["vol"] * 5.0, 0.0025)))
            for k, v in votes.items()
        }

    def learn(self, market, f, votes):
        self.learning.record_observation(market.market_id, f["price"], save=False)
        # Calibrated confidence reduces Brier-score distortion from overly
        # strong raw votes. It is intentionally capped below 0.70.
        mean_strength = sum(abs(v) for v in votes.values()) / max(1, len(votes))
        conf = min(0.68, 0.54 + 0.14 * mean_strength)
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
        agent_map = {
            "momentum-v3": "momentum",
            "mean_reversion-v3": "mean_reversion",
            "event_driven-v3": "event_driven",
            "mcx_commodity_specialist-v3": "mcx",
            "cross_market_arbitrage-v3": "arbitrage",
        }
        for agent_name, vote in votes.items():
            ui_agent = agent_map.get(agent_name, "research")
            label = "BUY" if vote > 0.05 else "SELL" if vote < -0.05 else "NEUTRAL"
            hq_events.status(**{ui_agent: "WORKING"})
            hq_events.activity(
                ui_agent,
                f"{market.tradingsymbol}: evaluating {label} ({vote:+.2f})",
                move=True,
            )
        hq_events.market(
            market.tradingsymbol,
            round(float(market.last_price), 8),
            provider=getattr(self.feed, "data_label", "unknown"),
            free_data=bool(getattr(self.feed, "is_free_data", False)),
            exchange=getattr(market, "exchange", None),
            quote_timestamp=getattr(market, "quote_timestamp", None),
        )
        if market.market_id in self._hq_candle_ids:
            hq_events.candles(
                market.tradingsymbol,
                self._feature_candles.get(market.market_id, []),
                provider=getattr(self.feed, "data_label", "unknown"),
                interval=os.getenv("MARKET_INTERVAL", os.getenv("NSE_INTERVAL", "5m")),
            )
        hq_events.snapshot(market.tradingsymbol, f, votes)

    def signal(self, market, f, votes):
        qualified, _ = self.learning.qualified_agents(list(votes.keys()))
        q = set(qualified)
        usable = [v for a, v in votes.items() if a in q and abs(v) > 0.05]
        if len(q) < MIN_AGENTS or len(usable) < MIN_AGENTS:
            hq_events.activity(
                "chief",
                f"{market.tradingsymbol}: waiting for {MIN_AGENTS} qualified specialists",
                move=False,
            )
            return None
        regime = classify_regime(f)
        hq_events.activity(
            "chief",
            f"{market.tradingsymbol}: opening specialist debate",
            move=True,
        )
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
            votes=debate.votes,
            qualified_agents=qualified,
        )
        hq_events.snapshot(
            market.tradingsymbol,
            f,
            votes,
            decision=debate.decision,
            agreement=round(float(debate.agreement), 4),
            conflict=round(float(debate.conflict), 4),
            score=round(float(debate.score), 4),
            confidence=round(float(debate.confidence), 4),
            debate=debate.rationale,
        )
        if debate.challenges:
            for challenge in debate.challenges:
                hq_events.activity("redteam", f"{market.tradingsymbol}: {challenge}", move=True)
        hq_events.activity(
            "risk",
            f"{market.tradingsymbol}: agreement={debate.agreement:.2f} conflict={debate.conflict:.2f}",
            move=True,
        )
        if debate.decision == "NO_TRADE":
            hq_events.activity("chief", f"{market.tradingsymbol}: NO TRADE", move=True)
            return None
        if regime.direction and debate.direction != regime.direction and regime.confidence >= 0.70:
            self.journal.record("REGIME_BLOCK", symbol=market.tradingsymbol, regime=regime.name)
            hq_events.activity("risk", f"{market.tradingsymbol}: blocked by strong regime mismatch", move=True)
            hq_events.activity("chief", f"{market.tradingsymbol}: regime block", move=True)
            return None
        if debate.score < MIN_SCORE or debate.confidence < MIN_CONF:
            hq_events.activity(
                "risk",
                f"{market.tradingsymbol}: score/confidence below threshold",
                move=True,
            )
            hq_events.activity("chief", f"{market.tradingsymbol}: rejected by thresholds", move=True)
            return None
        stop = max(0.003, min(0.02, 2.0 * f["vol"]))
        decision = "BUY" if debate.direction > 0 else "SELL"
        hq_events.activity(
            "chief",
            f"{market.tradingsymbol}: approved {decision} confidence={debate.confidence:.2f}",
            move=True,
        )
        return Signal(
            market, debate.direction, debate.score, debate.confidence, stop,
            "debate-approved: " + debate.rationale,
            features=dict(f),
            agent_votes=dict(votes),
        )

    def _mcx_generation_signal(self, generation, market):
        """Deterministic per-generation strategy variant; paper mode only."""
        features = self.features(market)
        if not features:
            return 0
        votes = self.agent_votes(features, market)
        # GENs use different strategy mixes, not the same copied signal.
        variants = (
            {"momentum-v3": 0.40, "mean_reversion-v3": 0.10, "event_driven-v3": 0.20, "mcx_commodity_specialist-v3": 0.20, "cross_market_arbitrage-v3": 0.10},
            {"momentum-v3": 0.15, "mean_reversion-v3": 0.40, "event_driven-v3": 0.10, "mcx_commodity_specialist-v3": 0.20, "cross_market_arbitrage-v3": 0.15},
            {"momentum-v3": 0.20, "mean_reversion-v3": 0.10, "event_driven-v3": 0.40, "mcx_commodity_specialist-v3": 0.20, "cross_market_arbitrage-v3": 0.10},
            {"momentum-v3": 0.15, "mean_reversion-v3": 0.15, "event_driven-v3": 0.10, "mcx_commodity_specialist-v3": 0.45, "cross_market_arbitrage-v3": 0.15},
            {"momentum-v3": 0.20, "mean_reversion-v3": 0.15, "event_driven-v3": 0.15, "mcx_commodity_specialist-v3": 0.15, "cross_market_arbitrage-v3": 0.35},
        )
        weights = variants[(int(generation) - 1) % len(variants)]
        score = sum(votes.get(name, 0.0) * weight for name, weight in weights.items())
        if abs(score) < float(os.getenv("MCX_GEN_SIGNAL_THRESHOLD", "0.18")):
            return 0
        return {"direction": 1 if score > 0 else -1, "stop_pct": max(0.003, min(0.02, 2.0 * features["vol"]))}

    def _run_mcx_tournament_paper_cycle(self, markets):
        bridge = getattr(self, "mcx_paper_bridge", None)
        if bridge is None or self.execution.enabled:
            return None
        # Bound expensive candle-history calls per GEN; full market discovery
        # remains separate from the configured strategy-evaluation budget.
        limit = max(1, int(os.getenv("MCX_TOURNAMENT_MARKETS_PER_CYCLE", "50")))
        selected = list(markets[:limit])
        try:
            result = bridge.run_cycle(
                selected,
                self._mcx_generation_signal,
                quote_age_seconds=(
                    getattr(self.feed, "freshness_seconds", None)
                    if self.backend == "angelone_mcx" else None
                ),
            )
            self.journal.record("MCX_GEN_PAPER_CYCLE", **result)
            print("[MCX_GEN_PAPER_CYCLE]", json.dumps(result, sort_keys=True))
            controller = getattr(self, "gen_evolution", None)
            if controller is not None:
                state = controller.tick()
                self.journal.record("MCX_GEN_EVOLUTION", **state)
                hq_events.emit("gen_tournament", **state)
                if state.get("status") == "CHAMPION_RUNNING":
                    hq_events.activity(
                        "chief",
                        "GEN champion selected: GEN-%s (paper qualification only)" % state.get("champion_generation"),
                        move=True,
                    )
                elif state.get("status") == "NO_QUALIFIED_CHAMPION":
                    hq_events.activity("risk", "GEN deadline reached without a qualified champion", move=True)
            return result
        except Exception as exc:
            self.journal.record("MCX_GEN_PAPER_CYCLE_BLOCKED", error=repr(exc))
            print("[MCX_GEN_PAPER_CYCLE] blocked", repr(exc))
            return None

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
                fee_bps = max(0.0, float(os.getenv("PAPER_FEE_BPS", "0")))
                pnl -= (float(position["entry"]) + exit_price) * float(position["qty"]) * fee_bps / 10000.0
                self.realized_pnl += pnl
                self.daily_realized_pnl += pnl
                closed.append((market_id, reason, pnl, exit_price))
                self._record_tournament_trade(position, pnl, reason, prices)
                self.journal.record(
                    "PAPER_EXIT",
                    symbol=market_id,
                    reason=reason,
                    pnl=pnl,
                    exit_price=exit_price,
                )
                hq_events.emit("trade", action="CLOSE",
                               symbol=position.get("tradingsymbol", market_id),
                               side="SELL" if position["side"] == "BUY" else "BUY",
                               quantity=position["qty"], price=round(exit_price, 4),
                               pnl=round(pnl, 2), reason=reason, paper=True)
                del self.open_positions[market_id]
                self._paper_agent_loss(
                    market_id, pnl, reason, position=position, exit_price=exit_price
                )
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
            fee_bps = max(0.0, float(os.getenv("PAPER_FEE_BPS", "0")))
            pnl -= (float(position["entry"]) + exit_price) * float(position["qty"]) * fee_bps / 10000.0
            self.realized_pnl += pnl
            self.daily_realized_pnl += pnl
            closed.append((market_id, reason, pnl, exit_price))
            self._record_tournament_trade(position, pnl, reason, prices)
            self.journal.record(
                "PAPER_EXIT",
                symbol=market_id,
                reason=reason,
                pnl=pnl,                exit_price=exit_price,
            )
            del self.open_positions[market_id]
        if closed:
            equity = self._paper_equity(prices)
            self.daily_pnl = self.daily_realized_pnl
            self.peak = max(self.peak, equity)
            for market_id, why, pnl, price in closed:
                print("[PAPER_SESSION_EXIT]", market_id, why,
                      "pnl=%.2f" % pnl, "price=%.2f" % price)
        return len(closed)

    def _record_tournament_trade(self, position, pnl, reason, prices=None):
        """Persist each closed MCX paper trade in its generation scorecard."""
        if self.tournament is None or self.execution.enabled:
            return None
        generation = int(position.get("generation", self.paper_generation))
        try:
            risk = self._paper_risk_snapshot(prices or {})
            card = self.tournament.record_trade(
                generation, float(pnl),
                timestamp=datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(),
                drawdown_fraction=float(risk.get("drawdown_fraction", 0.0)),
            )
            self.journal.record("MCX_TOURNAMENT_SCORECARD", **card, exit_reason=reason)
            print("[MCX_TOURNAMENT]", json.dumps(card, sort_keys=True))
            if card.get("status") == "RETIRED":
                hq_events.activity("chief", f"GEN-{generation} retired by tournament: {card.get('retirement_reason')}", move=True)
            elif card.get("promotion_eligible"):
                hq_events.activity("chief", f"GEN-{generation} reached tournament objective; champion review eligible", move=True)
            return card
        except ValueError as exc:
            self.journal.record("MCX_TOURNAMENT_RECORD_BLOCKED", generation=generation, error=str(exc))
            print("[MCX_TOURNAMENT] record blocked", repr(exc))
            return None

    def _paper_agent_loss(self, market_id, pnl, reason, position=None, exit_price=None):
        """Retire a losing paper generation and pass a structured trade autopsy forward."""
        if pnl >= 0 or self.execution.enabled:
            return
        position = position or {}
        entry_price = float(position.get("entry", 0.0) or 0.0)
        exit_value = float(exit_price or 0.0)
        side = str(position.get("side", "UNKNOWN")).upper()
        signed = 1 if side == "BUY" else -1 if side == "SELL" else 0
        directional_move_pct = (
            100.0 * signed * (exit_value - entry_price) / entry_price
            if entry_price > 0 and exit_value > 0 else None
        )
        raw_features = position.get("features") or {}
        feature_snapshot = {
            str(key): round(float(value), 6)
            for key, value in raw_features.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        raw_votes = position.get("agent_votes") or {}
        agent_votes = {
            str(key): round(float(value), 6)
            for key, value in raw_votes.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        previous = self.paper_generation
        autopsy = {
            "generation": previous,
            "market_id": market_id,
            "tradingsymbol": position.get("tradingsymbol", market_id),
            "side": side,
            "entry_price": round(entry_price, 6) if entry_price > 0 else None,
            "exit_price": round(exit_value, 6) if exit_value > 0 else None,
            "quantity": position.get("qty"),
            "pnl": round(float(pnl), 2),
            "directional_move_pct": round(directional_move_pct, 6) if directional_move_pct is not None else None,
            "exit_reason": reason,
            "entry_score": position.get("score"),
            "entry_confidence": position.get("confidence"),
            "stop_pct": position.get("stop_pct"),
            "entry_features": feature_snapshot,
            "agent_votes": agent_votes,
            "lesson": (
                "Loss is evidence, not proof of a universal rule. Preserve the failed "
                "thesis and feature context; replacement strategies must validate on "
                "unseen data before promotion."
            ),
            "timestamp": datetime.now().isoformat(),
        }
        self.paper_agent_alive = False
        self.paper_agent_knowledge.append(autopsy)
        hq_events.activity("chief", f"Paper GEN-{previous} DIED after loss {market_id} ({pnl:.2f})", move=True)
        hq_events.agent_analysis(
            "chief", str(market_id),
            f"GEN-{previous} loss autopsy completed; replacement inherits accumulated knowledge",
            evidence=[f"loss={pnl:.2f}", f"exit={reason}", f"knowledge_items={len(self.paper_agent_knowledge)}"],
            action="REPLACE", adaptation="loss-autopsy + inherited-history + new-generation"
        )
        self.paper_generation = previous + 1
        if getattr(self, "tournament", None) is not None:
            self.tournament.ensure_generation(self.paper_generation, parent_generation=previous)
        self.paper_agent_alive = True
        hq_events.activity("chief", f"Paper GEN-{self.paper_generation} spawned with inherited knowledge", move=True)
        self.journal.record(
            "PAPER_AGENT_REPLACEMENT",
            dead_generation=previous,
            new_generation=self.paper_generation,
            loss=round(float(pnl), 2),
            market_id=market_id,
            inherited_knowledge=len(self.paper_agent_knowledge),
        )

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
            "total_paper_trades": self.total_paper_trades,
        }

    def paper_or_live(self, sig):
        m = sig.market
        capital = self.execution.funds_available(getattr(m, "exchange", "NSE")) if self.execution.enabled else self.cash
        if capital is None or capital <= 0:
            print("[risk] no available Zerodha equity margin; no order")
            return
        fractional_paper = os.getenv("PAPER_FRACTIONAL_UNITS", "false").lower() == "true"
        if fractional_paper and self.execution.enabled:
            raise RuntimeError("PAPER_FRACTIONAL_UNITS is paper-only; refusing live execution.")
        lot_size = max(1, int(getattr(m, "lot_size", 1) or 1))
        existing_notional = sum(
            abs(float(position.get("entry", 0.0) or 0.0) * float(position.get("qty", 0.0) or 0.0))
            for position in self.open_positions.values()
        )
        remaining_notional = max(0.0, capital * MAX_TOTAL_EXPOSURE - existing_notional)
        if not fractional_paper and remaining_notional < m.last_price:
            print("[risk] total exposure cap reached; no order")
            return
        risk_cap = capital * MAX_POSITION
        risk_per_unit = max(m.last_price * sig.stop_pct, 0.05)
        raw_qty = risk_cap / risk_per_unit if fractional_paper else int(risk_cap / risk_per_unit)
        max_notional = min(capital * MAX_POSITION, remaining_notional)
        qty = min(raw_qty, max_notional / m.last_price if fractional_paper else int(max_notional / m.last_price))
        if fractional_paper:
            qty = round(max(0.0, qty), 8)
        else:
            qty = (int(qty) // lot_size) * lot_size
        if qty <= 0:
            print("[risk] position size is below the supported minimum; no order")
            return
        side = "BUY" if sig.direction > 0 else "SELL"
        hq_events.activity(
            "risk",
            f"{m.tradingsymbol}: position sizing and exposure check",
            move=True,
        )
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
                raw_intent = f"{self.paper_cycle}:{m.market_id}:{side}:{qty}"
                intent_id = ("mcx-" if m.exchange == "MCX" else "nse-") + hashlib.sha256(raw_intent.encode()).hexdigest()[:12]
                if self.backend in {"angelone_nse", "angelone_mcx"}:
                    request = __import__("angelone_adapter").OrderRequest(
                        m.tradingsymbol,
                        str(m.instrument_token),
                        m.exchange,
                        side,
                        qty,
                        price,
                        os.getenv("ANGELONE_PRODUCT", "CARRYFORWARD" if self.backend == "angelone_mcx" else "INTRADAY"),
                        intent_id,
                    )
                else:
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
                    "tradingsymbol": m.tradingsymbol,
                    "generation": self.paper_generation,
                    "order_id": fill["order_id"],
                    "side": side,
                    "qty": filled,
                    "entry": avg_price,
                    "stop_pct": sig.stop_pct,
                    "entry_cycle": self.paper_cycle,
                    "score": sig.score,
                    "confidence": sig.confidence,
                    "reason": sig.reason,
                    "features": sig.features or {},
                    "agent_votes": sig.agent_votes or {},
                }
                self.traded_today.add(m.market_id)
                print("[ANGELONE_FILL]" if self.backend in {"angelone_nse", "angelone_mcx"} else "[ZERODHA_FILL]", fill)
            except Exception as exc:
                self.journal.record("ORDER_FAILURE", symbol=m.tradingsymbol, error=repr(exc))
                print("[angelone execution blocked]" if self.backend in {"angelone_nse", "angelone_mcx"} else "[zerodha execution blocked]", repr(exc))
        else:
            hq_events.activity(
                "chief",
                f"{m.tradingsymbol}: PAPER {side} prepared (live execution disabled)",
                move=True,
            )
            entry = self._paper_fill_price(m.last_price, side)
            self.open_positions[m.market_id] = {
                "market_id": m.market_id,
                "generation": self.paper_generation,
                "side": side,
                "qty": qty,
                "entry": entry,
                "stop_pct": sig.stop_pct,
                "entry_cycle": self.paper_cycle,
                "score": sig.score,
                "confidence": sig.confidence,
                "reason": sig.reason,
                "features": sig.features or {},
                "agent_votes": sig.agent_votes or {},
            }
            self.traded_today.add(m.market_id)
            self.total_paper_trades += 1
            hq_events.emit("trade", action="OPEN", symbol=m.tradingsymbol, side=side,
                           quantity=qty, price=round(entry, 4),
                           score=round(sig.score, 4), confidence=round(sig.confidence, 4), paper=True)
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
            if p.get("exchange") != getattr(self.feed, "exchange", os.getenv("TRADING_EXCHANGE", "NSE")):
                continue
            qty = int(p.get("quantity", 0) or 0)
            if qty:
                broker[p.get("tradingsymbol")] = qty
        local = {}
        for p in self.open_positions.values():
            qty = int(p.get("qty", 0) or 0)
            if qty:
                signed = qty if p.get("side") == "BUY" else -qty
                key = p.get("tradingsymbol", p.get("market_id"))
                local[key] = local.get(key, 0) + signed
        if set(local) != set(broker):
            self.journal.record("RECONCILIATION_FAILURE", local=local, broker=broker)
            return False
        for symbol, qty in broker.items():
            local_qty = 0
            for p in self.open_positions.values():
                if p.get("tradingsymbol", p.get("market_id")) == symbol:
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
        session_end_hour = int(os.getenv("MARKET_SESSION_END_HOUR", "23" if os.getenv("TRADING_BACKEND","").lower() in {"mcx","angelone_mcx"} else "15"))
        session_end_minute = int(os.getenv("MARKET_SESSION_END_MINUTE", "20" if os.getenv("TRADING_BACKEND","").lower() in {"mcx","angelone_mcx"} else "15"))
        session_end = (now_ist.hour > session_end_hour or (now_ist.hour == session_end_hour and now_ist.minute >= session_end_minute))

        if session_end and not self.execution.enabled and not self.open_positions:
            print("[paper] MCX session closed; no after-hours paper cycle." if self.backend in {"mcx","angelone_mcx"} else "[paper] NSE session closed; no after-hours paper cycle.")
            self._save_paper_state()
            return

        if self.execution.enabled and session_end:
            try:
                self.execution.exit_all_intraday(getattr(self.feed, "exchange", os.getenv("TRADING_EXCHANGE", "NSE")))
                self.open_positions.clear()
                print("[zerodha] intraday exit window reached; positions squared off")
            except Exception as exc:
                print("[zerodha exit] recovered", repr(exc))
            return

        hq_events.heartbeat("Trading engine cycle started")
        hq_events.activity(
            "research",
            "Scanning market universe",
            move=True,
        )
        print("\n[%s] %s scanning..." % (datetime.now().isoformat(timespec="seconds"), "MCX" if self.backend in {"mcx","angelone_mcx"} else "NSE"))
        markets = self.feed.fetch(int(os.getenv("MAX_MARKETS_PER_SCAN", "1000")))
        if self.backend in {"mcx", "angelone_mcx"}:
            city_rows = []
            for market in markets:
                city_rows.append({
                    "symbol": getattr(market, "tradingsymbol", ""),
                    "exchange": getattr(market, "exchange", ""),
                    "instrument_type": ("FUT" if getattr(self.feed, "is_live_authorized_data", False) else "PROXY"),
                    "quote_timestamp": getattr(market, "quote_timestamp", None),
                    "last_price": getattr(market, "last_price", None),
                    "lot_size": getattr(market, "lot_size", None),
                })
            from trading_city import build_market_universe
            city_universe = build_market_universe(city_rows, max_quote_age_seconds=MAX_LIVE_DATA_AGE)
            self.city.update_universe(city_universe)
            hq_events.emit("market_universe", **city_universe)
        self._hq_candle_ids = {m.market_id for m in markets[:int(os.getenv("HQ_CANDLE_PREVIEW_LIMIT", "5"))]}
        self._feature_candles.clear()
        print("[market] market universe scanned=", len(markets))
        hq_events.activity("research", f"Scanned {len(markets)} markets", move=True)
        for market_item in markets[:int(os.getenv("HQ_MARKET_PREVIEW_LIMIT", "5"))]:
            hq_events.market(market_item.tradingsymbol, round(float(market_item.last_price), 4))
        prices = {m.market_id: m.last_price for m in markets}
        if not self.execution.enabled:
            self.feed.prefetch_history(markets, days=2, interval=os.getenv("MARKET_INTERVAL", os.getenv("NSE_INTERVAL", "5m")))
            hq_events.activity("chief", f"Paper evolution GEN-{self.paper_generation}: inherited knowledge={len(self.paper_agent_knowledge)}", move=True)

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
            metrics = self.paper_metrics(prices)
            hq_events.emit("portfolio", **metrics)
            self._save_paper_state()
            print("[paper]", metrics)
            return

        if self.execution.enabled:
            if not self.feed.is_live_authorized_data:
                raise AngelOneLocked("Live execution requires an authorised market-data provider.")
            stale = [m.tradingsymbol for m in markets if self.feed.freshness_seconds(m) > MAX_LIVE_DATA_AGE]
            if stale:
                raise ZerodhaLocked(f"Live execution blocked: market data is stale for {len(stale)} symbols.")
        resolved = self.learning.resolve(prices.get)
        qualified, learning_details = self.learning.qualified_agents(
            [
                "momentum-v3",
                "mean_reversion-v3",
                "event_driven-v3",
                "mcx_commodity_specialist-v3",
                "cross_market_arbitrage-v3",
            ]
        )
        # Send the actual learning state to HQ: forecast counts, accuracy,
        # Brier score, recent stability, qualification and adaptive weight.
        last_resolved = []
        for item in self.learning.data.get("history", [])[-20:]:
            last_resolved.append({
                "market_id": item.get("market_id"),
                "outcome": item.get("outcome"),
                "realized_move": item.get("realized_move"),
                "resolved_at": item.get("resolved_at"),
                "directions": item.get("directions", {}),
            })
        hq_events.learning(
            qualified=qualified,
            details=learning_details,
            resolved=resolved,
            history=len(self.learning.data["history"]),
            observations=self.learning.observation_count(),
            last_resolved=last_resolved,
            horizon_seconds=HORIZON,
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
        if self.backend == "angelone_mcx":
            # MCX live mode evaluates every instrument returned by the full
            # configured quote scan; do not silently truncate to a small
            # MARKETS_PER_CYCLE value.
            research_limit = len(markets)
        else:
            research_limit = int(
                os.getenv(
                    "MARKETS_PER_CYCLE",
                    os.getenv(
                        "NSE_RESEARCH_MARKETS_PER_CYCLE",
                        "25" if self.execution.enabled else "1000",
                    ),
                )
            )
        for m in markets[:max(1, research_limit)]:
            try:
                f = self.features(m)
                if not f:
                    continue
                votes = self.agent_votes(f, m)
                agent_ui = {
                    "momentum-v3": "momentum",
                    "mean_reversion-v3": "mean_reversion",
                    "event_driven-v3": "event_driven",
                    "mcx_commodity_specialist-v3": "mcx",
                    "cross_market_arbitrage-v3": "arbitrage",
                }
                for agent_name, vote in votes.items():
                    ui_agent = agent_ui.get(agent_name, "research")
                    direction = "BUY" if vote > 0.05 else "SELL" if vote < -0.05 else "NEUTRAL"
                    stats = self.learning.stats(agent_name)
                    weight = self.learning.weight(agent_name)
                    adaptation = "boosted" if weight > 1.02 else "reduced" if weight < 0.98 else "baseline"
                    evidence = []
                    if f["r10"] > 0: evidence.append("10-bar momentum positive")
                    elif f["r10"] < 0: evidence.append("10-bar momentum negative")
                    if f["rsi"] >= 65: evidence.append("RSI elevated")
                    elif f["rsi"] <= 35: evidence.append("RSI depressed")
                    if f["breakout"] > 0: evidence.append("breakout pressure")
                    if f["breakdown"] < 0: evidence.append("breakdown pressure")
                    if f["volume_ratio"] > 1.25: evidence.append("volume expansion")
                    thesis = f"{direction} thesis from live feature evidence; vote {vote:+.3f}"
                    hq_events.agent_analysis(
                        ui_agent, m.tradingsymbol, thesis,
                        evidence=evidence[:4], action=direction,
                        confidence=stats.get("recent_accuracy"),
                        adaptation=adaptation,
                    )
                    hq_events.activity(
                        ui_agent,
                        f"{m.tradingsymbol}: {direction} thesis; {adaptation} weight",
                        move=True,
                    )
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
        if self.backend in {"mcx", "angelone_mcx"} and not self.execution.enabled:
            self._run_mcx_tournament_paper_cycle(markets)
        self.learning._save()
        if not self.execution.enabled:
            self._save_paper_state()
        if not self.execution.enabled:
            metrics = self.paper_metrics(prices)
            hq_events.emit("portfolio", **metrics)
            print("[paper]", metrics)
        hq_events.status(
            momentum="MONITORING",
            mean_reversion="MONITORING",
            event_driven="MONITORING",
            mcx="MONITORING",
            arbitrage="MONITORING",
            research="MONITORING",
            redteam="MONITORING",
            risk="MONITORING",
            chief="MONITORING",
        )
        try:
            # Mirror the actual evolution controller state instead of resetting
            # the HQ tournament to RUNNING on every engine cycle.
            controller = getattr(self, "gen_evolution", None)
            if controller is not None:
                evolution = dict(getattr(controller, "state", {}) or {})
                evolution_status = str(evolution.get("status") or "RUNNING").upper()
                champion_generation = evolution.get("champion_generation")
                champion_id = (
                    "GEN-%s" % champion_generation
                    if champion_generation is not None else None
                )
                self.city.update_tournament(
                    stage="GEN_TOURNAMENT",
                    status=evolution_status,
                    champion_id=champion_id,
                )
                hq_events.emit(
                    "gen_tournament",
                    status=evolution_status,
                    champion_generation=champion_generation,
                    result=evolution.get("result"),
                    deadline_at=evolution.get("deadline_at"),
                    session_generations=evolution.get("session_generations", []),
                )
            else:
                self.city.update_tournament(stage="GEN_TOURNAMENT", status="RUNNING")
            hq_events.emit("trading_city", **self.city.snapshot())
        except Exception as city_error:
            self.city.record_error(str(city_error))
            hq_events.emit("trading_city_error", error=str(city_error)[:300])
        hq_events.heartbeat("Trading engine cycle complete")
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
            cycle_started = time.monotonic()
            try:
                self.cycle()
            except Exception as exc:
                print("[nse supervisor] recovered", repr(exc))
            # Keep scan starts approximately SCAN_SECONDS apart. Sleeping a
            # full interval after a slow cycle would silently stretch cadence.
            remaining = SCAN_SECONDS - (time.monotonic() - cycle_started)
            if remaining > 0:
                time.sleep(remaining)


if __name__ == "__main__":
    NSETradingCompany().run()