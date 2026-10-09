"""Persistent paper tournament scorecards and guarded promotion state machine.

This module ranks virtual strategy generations and records promotion eligibility.
It never enables broker live execution. A human/configuration gate must separately
approve any live candidate after Angel One validation and broker safety checks.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import os
import tempfile


STAGES = ("GEN_TOURNAMENT", "ANGELONE_PAPER_VALIDATION", "LIVE_CANDIDATE", "RETIRED")


def _utc_now():
    return datetime.now(timezone.utc)


def _parse_time(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


class TournamentLedger:
    """Track net trade outcomes, one-hour metrics, champions and validation gates."""

    def __init__(self, path="data/mcx_tournament.json", target_pnl=1000.0,
                 window_seconds=3600, min_trades=3, max_drawdown_fraction=0.10):
        self.path = path
        self.target_pnl = float(target_pnl)
        self.window_seconds = int(window_seconds)
        self.min_trades = max(1, int(min_trades))
        self.max_drawdown_fraction = float(max_drawdown_fraction)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.state = self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                state = json.load(handle)
            if isinstance(state, dict) and isinstance(state.get("generations"), dict):
                state.setdefault("promotions", [])
                state.setdefault("champion_generation", None)
                return state
        except (OSError, ValueError, TypeError):
            pass
        return {"generations": {}, "promotions": [], "champion_generation": None}

    def _save(self):
        parent = os.path.dirname(self.path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".tournament-", suffix=".tmp", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.state, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def ensure_generation(self, generation, parent_generation=None):
        key = str(int(generation))
        if key not in self.state["generations"]:
            self.state["generations"][key] = {
                "generation": int(generation),
                "parent_generation": parent_generation,
                "stage": "GEN_TOURNAMENT",
                "status": "ACTIVE",
                "trades": [],
                "created_at": _utc_now().isoformat(),
                "retirement_reason": None,
                "validation": None,
            }
            self._save()
        return self.state["generations"][key]

    def record_trade(self, generation, pnl, *, fees=0.0, slippage=0.0,
                     timestamp=None, drawdown_fraction=0.0, rule_violation=False):
        """Record one closed trade. pnl is gross; fees/slippage are deducted here."""
        record = self.ensure_generation(generation)
        if record["status"] != "ACTIVE" or record["stage"] != "GEN_TOURNAMENT":
            raise ValueError("cannot add GEN trades to a non-active tournament generation")
        at = _parse_time(timestamp or _utc_now().isoformat())
        gross = float(pnl)
        fees, slippage = max(0.0, float(fees)), max(0.0, float(slippage))
        net = gross - fees - slippage
        record["trades"].append({
            "timestamp": at.isoformat(), "gross_pnl": round(gross, 6),
            "fees": round(fees, 6), "slippage": round(slippage, 6),
            "net_pnl": round(net, 6),
            "drawdown_fraction": max(0.0, float(drawdown_fraction)),
            "rule_violation": bool(rule_violation),
        })
        record["trades"] = record["trades"][-5000:]
        if net < 0 or rule_violation:
            record["status"] = "RETIRED"
            record["stage"] = "RETIRED"
            record["retirement_reason"] = "loss" if net < 0 else "risk_rule_violation"
            record["retired_at"] = at.isoformat()
        self._save()
        return self.scorecard(generation, now=at)

    def scorecard(self, generation, now=None):
        record = self.state["generations"].get(str(int(generation)))
        if not record:
            raise KeyError("unknown generation")
        now = _parse_time(now or _utc_now().isoformat())
        cutoff = now - timedelta(seconds=self.window_seconds)
        trades = [t for t in record["trades"] if cutoff <= _parse_time(t["timestamp"]) <= now]
        net_values = [float(t["net_pnl"]) for t in trades]
        wins = sum(1 for value in net_values if value > 0)
        pnl = sum(net_values)
        peak = 0.0
        cumulative = 0.0
        max_dd_cash = 0.0
        for value in net_values:
            cumulative += value
            peak = max(peak, cumulative)
            max_dd_cash = max(max_dd_cash, peak - cumulative)
        reported_dd = max((float(t.get("drawdown_fraction", 0.0)) for t in trades), default=0.0)
        # A generation only becomes a candidate if target, sample size, stability,
        # and risk gates all pass. A single loss retires it before promotion.
        target_hit = pnl >= self.target_pnl
        enough_trades = len(trades) >= self.min_trades
        no_rule_violations = not any(t.get("rule_violation") for t in trades)
        eligible = (target_hit and enough_trades and record["status"] == "ACTIVE"
                    and reported_dd <= self.max_drawdown_fraction
                    and no_rule_violations and all(v >= 0 for v in net_values))
        return {
            "generation": int(generation), "stage": record["stage"], "status": record["status"],
            "window_seconds": self.window_seconds, "trades": len(trades),
            "net_pnl": round(pnl, 2), "gross_pnl": round(sum(float(t["gross_pnl"]) for t in trades), 2),
            "fees": round(sum(float(t["fees"]) for t in trades), 2),
            "slippage": round(sum(float(t["slippage"]) for t in trades), 2),
            "win_rate": round(wins / len(trades), 4) if trades else 0.0,
            "max_drawdown_cash": round(max_dd_cash, 2),
            "max_drawdown_fraction": round(reported_dd, 6),
            "target_pnl": self.target_pnl, "target_hit": target_hit,
            "enough_trades": enough_trades, "promotion_eligible": eligible,
            "retirement_reason": record.get("retirement_reason"),
        }

    def select_champion(self, now=None):
        """Choose the best eligible generation by risk-adjusted scorecard, not P&L alone."""
        candidates = []
        for key, record in self.state["generations"].items():
            if record["stage"] != "GEN_TOURNAMENT":
                continue
            card = self.scorecard(int(key), now=now)
            if card["promotion_eligible"]:
                # P&L first, then lower drawdown, then more trades as a stability tie-break.
                candidates.append((card["net_pnl"], -card["max_drawdown_fraction"],
                                   card["trades"], int(key), card))
        if not candidates:
            return None
        winner = max(candidates)[3]
        record = self.state["generations"][str(winner)]
        record["status"] = "PROMOTION_PENDING"
        self.state["champion_generation"] = winner
        self.state["promotions"].append({
            "generation": winner, "from": "GEN_TOURNAMENT",
            "to": "ANGELONE_PAPER_VALIDATION", "status": "PENDING",
            "created_at": _utc_now().isoformat(),
        })
        self._save()
        return {"generation": winner, "scorecard": self.scorecard(winner, now=now),
                "next_stage": "ANGELONE_PAPER_VALIDATION", "status": "PENDING"}

    def begin_angelone_validation(self, generation):
        record = self.state["generations"].get(str(int(generation)))
        if not record or record["status"] != "PROMOTION_PENDING" or int(generation) != self.state.get("champion_generation"):
            raise ValueError("only the selected GEN champion may enter Angel One paper validation")
        record["stage"] = "ANGELONE_PAPER_VALIDATION"
        record["status"] = "VALIDATING"
        self._save()
        return record

    def record_angelone_validation(self, generation, *, net_pnl, trades, duration_seconds,
                                   max_drawdown_fraction, data_source, actual_contract_sizing,
                                   stale_quote_events=0, risk_violations=0):
        """Record validation evidence; this still never enables live order submission."""
        record = self.state["generations"].get(str(int(generation)))
        if not record or record["stage"] != "ANGELONE_PAPER_VALIDATION" or record["status"] != "VALIDATING":
            raise ValueError("generation is not in Angel One paper validation")
        checks = {
            "angelone_data": str(data_source).lower() in {"angelone_mcx", "angelone_mcx_live_quotes"},
            "actual_contract_sizing": bool(actual_contract_sizing),
            "minimum_duration": float(duration_seconds) >= self.window_seconds,
            "minimum_trades": int(trades) >= self.min_trades,
            "positive_net_pnl": float(net_pnl) > 0,
            "drawdown_within_limit": 0 <= float(max_drawdown_fraction) <= self.max_drawdown_fraction,
            "no_stale_quote_events": int(stale_quote_events) == 0,
            "no_risk_violations": int(risk_violations) == 0,
        }
        passed = all(checks.values())
        record["validation"] = {
            "net_pnl": float(net_pnl), "trades": int(trades),
            "duration_seconds": float(duration_seconds),
            "max_drawdown_fraction": float(max_drawdown_fraction),
            "data_source": str(data_source), "actual_contract_sizing": bool(actual_contract_sizing),
            "stale_quote_events": int(stale_quote_events), "risk_violations": int(risk_violations),
            "checks": checks, "passed": passed, "timestamp": _utc_now().isoformat(),
        }
        record["status"] = "LIVE_CANDIDATE" if passed else "VALIDATION_FAILED"
        if passed:
            record["stage"] = "LIVE_CANDIDATE"
        else:
            record["stage"] = "RETIRED"
            record["retirement_reason"] = "angelone_validation_failed"
        for promotion in reversed(self.state["promotions"]):
            if promotion["generation"] == int(generation) and promotion["to"] == "ANGELONE_PAPER_VALIDATION":
                promotion["status"] = "PASSED" if passed else "FAILED"
                promotion["validation_checks"] = checks
                break
        self._save()
        return {"generation": int(generation), "passed": passed, "checks": checks,
                "live_orders_enabled": False, "next_stage": record["stage"]}

    def live_candidate(self):
        """Return readiness evidence only; callers must keep broker live gates separate."""
        candidates = [
            record for record in self.state["generations"].values()
            if record["stage"] == "LIVE_CANDIDATE" and record.get("validation", {}).get("passed")
        ]
        if not candidates:
            return None
        return {"generation": max(candidates, key=lambda item: item["generation"])["generation"],
                "live_orders_enabled": False, "requires_separate_operator_approval": True}
