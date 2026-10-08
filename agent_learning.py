"""Conservative online learning for paper-mode trading agents.

Learns from out-of-sample next-horizon price moves and records enough
diagnostics to reward stable agents while suppressing unstable ones. Learning
never authorizes a trade by itself.
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

from strategy_validation import walk_forward_report


class AgentLearningStore:
    def __init__(self, path=None, horizon_seconds=None, max_pending=5000,
                 max_history=10000, max_no_move_retries=6):
        state_root = "/data" if os.path.isdir("/data") else "."
        self.path = path or os.getenv("AGENT_LEARNING_FILE",
                                      os.path.join(state_root, "agent_learning.json"))
        self.horizon_seconds = int(
            horizon_seconds if horizon_seconds is not None
            else os.getenv("AGENT_LEARNING_HORIZON_SECONDS", "300")
        )
        self.max_pending = max(100, int(max_pending))
        self.max_history = max(1000, int(max_history))
        self.max_no_move_retries = max(
            1, int(os.getenv("LEARNING_MAX_NO_MOVE_RETRIES", max_no_move_retries))
        )
        Path(os.path.dirname(self.path) or ".").mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self):
        default = {"pending": [], "history": [], "agents": {}, "observations": {}}
        if not os.path.exists(self.path):
            return default
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return default
            for key in ("pending", "history"):
                if not isinstance(raw.get(key), list):
                    raw[key] = []
            for key in ("agents", "observations"):
                if not isinstance(raw.get(key), dict):
                    raw[key] = {}
            return raw
        except Exception:
            return default

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    @staticmethod
    def _direction(vote):
        return 1 if float(vote) > 0 else -1 if float(vote) < 0 else 0

    def record_observation(self, market_id, price, now=None, max_points=120, save=True):
        try:
            price = float(price)
        except (TypeError, ValueError):
            return
        if not math.isfinite(price) or price <= 0:
            return
        now = float(now if now is not None else time.time())
        key = str(market_id)
        rows = self.data["observations"].setdefault(key, [])
        if rows and abs(float(rows[-1].get("price", 0.0)) - price) < 1e-9:
            rows[-1]["time"] = now
        else:
            rows.append({"time": now, "price": price})
        self.data["observations"][key] = rows[-max(8, int(max_points)):]
        if save:
            self._save()

    def history_for_market(self, market_id):
        rows = self.data["observations"].get(str(market_id), [])
        return [float(x["price"]) for x in rows if isinstance(x, dict) and "price" in x]

    def record_forecast(self, market_id, question, price, votes, confidence, edge, now=None,
                        context=None):
        now = float(now if now is not None else time.time())
        directions = {
            agent: self._direction(vote)
            for agent, vote in (votes or {}).items()
            if self._direction(vote) != 0
        }
        if not directions:
            return
        bucket = int(now // max(1, self.horizon_seconds))
        market_key = str(market_id)
        direction_key = tuple(sorted(directions))
        for item in self.data["pending"]:
            existing_directions = tuple(sorted((item.get("directions") or {}).keys()))
            if (
                str(item.get("market_id")) == market_key
                and int(float(item.get("created_at", 0)) // max(1, self.horizon_seconds)) == bucket
                and existing_directions == direction_key
            ):
                return
        self.data["pending"].append({
            "created_at": now,
            "resolve_after": now + self.horizon_seconds,
            "market_id": market_key,
            "question": question,
            "price": float(price),
            "edge": float(edge),
            "confidence": float(confidence),
            "directions": directions,
            "context": context or {},
            "no_move_retries": 0,
        })
        self.data["pending"] = self.data["pending"][-self.max_pending:]
        self._save()

    def _record_agent(self, agent, direction, outcome, confidence):
        if outcome == 0:
            return
        d = self.data["agents"].setdefault(agent, {
            "forecasts": 0, "correct": 0, "incorrect": 0,
            "brier_sum": 0.0, "recent": [], "last_updated": None,
        })
        d["forecasts"] += 1
        correct = direction == outcome
        d["correct"] += int(correct)
        d["incorrect"] += int(not correct)
        confidence = min(0.95, max(0.50, float(confidence)))
        d["brier_sum"] += (confidence - (1.0 if correct else 0.0)) ** 2
        recent = d.setdefault("recent", [])
        recent.append({"correct": bool(correct), "time": time.time()})
        d["recent"] = recent[-50:]
        d["last_updated"] = time.time()

    def resolve(self, price_lookup, now=None):
        now = float(now if now is not None else time.time())
        remaining = []
        resolved = 0
        for item in self.data["pending"]:
            if item.get("resolve_after", 0) > now:
                remaining.append(item)
                continue
            try:
                current = price_lookup(item["market_id"])
                if current is None:
                    remaining.append(item)
                    continue
                current = float(current)
                previous = float(item["price"])
                move_mode = os.getenv("LEARNING_MOVE_MODE", "relative").lower()
                if move_mode == "relative":
                    threshold = float(os.getenv("LEARNING_MIN_MOVE_PCT", "0.001"))
                    move = abs(current - previous) / max(abs(previous), 1e-12)
                else:
                    threshold = float(os.getenv("LEARNING_MIN_MOVE", "0.005"))
                    move = abs(current - previous)
                if move < threshold:
                    retries = int(item.get("no_move_retries", 0)) + 1
                    if retries <= self.max_no_move_retries:
                        item["no_move_retries"] = retries
                        item["resolve_after"] = now + self.horizon_seconds
                        remaining.append(item)
                        continue
                    item["resolved_at"] = now
                    item["outcome"] = 0
                    item["neutral"] = True
                    self.data["history"].append(item)
                    resolved += 1
                    continue
                outcome = 1 if current > previous else -1
                for agent, direction in item.get("directions", {}).items():
                    self._record_agent(agent, direction, outcome, item.get("confidence", 0.5))
                item["resolved_at"] = now
                item["outcome"] = outcome
                item["resolved_price"] = current
                item["realized_move"] = (current - previous) / max(abs(previous), 1e-12)
                self.data["history"].append(item)
                resolved += 1
            except Exception:
                remaining.append(item)
        self.data["pending"] = remaining[-self.max_pending:]
        self.data["history"] = self.data["history"][-self.max_history:]
        self._save()
        return resolved

    def stats(self, agent):
        d = self.data["agents"].get(agent, {})
        n = int(d.get("forecasts", 0))
        recent = d.get("recent", [])[-20:]
        recent_accuracy = (
            sum(bool(x.get("correct")) for x in recent) / len(recent)
            if recent else None
        )
        return {
            "forecasts": n,
            "accuracy": (d.get("correct", 0) / n) if n else None,
            "brier": (d.get("brier_sum", 0.0) / n) if n else None,
            "recent_accuracy": recent_accuracy,
        }

    def validation_report(self, agent, minimum_samples=None, minimum_accuracy=None, maximum_brier=None):
        minimum_samples = int(os.getenv("LEARNING_MIN_SAMPLES", "30")) if minimum_samples is None else int(minimum_samples)
        minimum_accuracy = float(os.getenv("LEARNING_MIN_ACCURACY", "0.55")) if minimum_accuracy is None else float(minimum_accuracy)
        maximum_brier = float(os.getenv("LEARNING_MAX_BRIER", "0.25")) if maximum_brier is None else float(maximum_brier)
        return walk_forward_report(
            self.data.get("history", []), agent,
            test_size=int(os.getenv("LEARNING_WALK_FORWARD_TEST_SIZE", "10")),
            min_train_samples=int(os.getenv("LEARNING_WALK_FORWARD_MIN_TRAIN", "10")),
            min_windows=int(os.getenv("LEARNING_WALK_FORWARD_MIN_WINDOWS", "2")),
            recent_size=int(os.getenv("LEARNING_RECENT_SAMPLES", "10")),
            min_recent_accuracy=float(os.getenv("LEARNING_MIN_RECENT_ACCURACY", "0.50")),
            max_recent_accuracy_drop=float(os.getenv("LEARNING_MAX_RECENT_ACCURACY_DROP", "0.15")),
            min_accuracy=minimum_accuracy, max_brier=maximum_brier,
        )

    def qualification(self, agent, minimum_samples=None, minimum_accuracy=None, maximum_brier=None):
        minimum_samples = int(os.getenv("LEARNING_MIN_SAMPLES", "30")) if minimum_samples is None else int(minimum_samples)
        minimum_accuracy = float(os.getenv("LEARNING_MIN_ACCURACY", "0.55")) if minimum_accuracy is None else float(minimum_accuracy)
        maximum_brier = float(os.getenv("LEARNING_MAX_BRIER", "0.25")) if maximum_brier is None else float(maximum_brier)
        stats = self.stats(agent)
        if stats["forecasts"] < minimum_samples:
            return False, "insufficient_samples", stats
        if stats["accuracy"] is None or stats["accuracy"] < minimum_accuracy:
            return False, "accuracy_below_threshold", stats
        if stats["brier"] is None or stats["brier"] > maximum_brier:
            return False, "brier_above_threshold", stats
        report = self.validation_report(agent, minimum_samples, minimum_accuracy, maximum_brier)
        stats = {**stats, "validation": report}
        if report["status"] != "validated":
            if report["walk_forward_windows"] < int(os.getenv("LEARNING_WALK_FORWARD_MIN_WINDOWS", "2")):
                return False, "walk_forward_insufficient_windows", stats
            if not report["recent_stable"]:
                return False, "recent_performance_unstable", stats
            return False, "walk_forward_validation_failed", stats
        return True, "validated_walk_forward", stats

    def qualified_agents(self, agent_ids, minimum_samples=None, minimum_accuracy=None, maximum_brier=None):
        qualified, details = [], {}
        for agent in agent_ids:
            ok, reason, stats = self.qualification(agent, minimum_samples, minimum_accuracy, maximum_brier)
            details[agent] = {"qualified": ok, "reason": reason, **stats}
            if ok:
                qualified.append(agent)
        return qualified, details

    def observation_count(self):
        return sum(len(rows) for rows in self.data.get("observations", {}).values())

    def weight(self, agent, minimum_samples=None):
        minimum_samples = int(os.getenv("LEARNING_MIN_SAMPLES", "30")) if minimum_samples is None else int(minimum_samples)
        stats = self.stats(agent)
        n = stats["forecasts"]
        if n < minimum_samples or stats["accuracy"] is None:
            return 1.0
        accuracy = float(stats["accuracy"])
        recent = stats.get("recent_accuracy")
        # Stable agents receive a small boost; recent deterioration removes it.
        weight = 1.0 + (accuracy - 0.50) * 1.2
        if recent is not None:
            weight += max(-0.15, min(0.10, (recent - accuracy) * 0.5))
        return max(0.70, min(1.30, weight))

    def learning_snapshot(self, agent_ids):
        qualified, details = self.qualified_agents(agent_ids)
        return {
            "qualified": qualified,
            "details": details,
            "weights": {agent: self.weight(agent) for agent in agent_ids},
        }

    def summary(self):
        return {
            "pending": len(self.data["pending"]),
            "resolved": len(self.data["history"]),
            "observations": self.observation_count(),
            "agents": {agent: self.stats(agent) for agent in sorted(self.data["agents"])},
        }
