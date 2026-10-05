"""Lightweight online forecast learning for paper-mode agents.

This module learns from *observed next-horizon price moves*, not from realized
trading P&L. It is deliberately separated from the trade gate: forecast
learning can improve agent weighting, but it can never authorize a trade.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


class AgentLearningStore:
    def __init__(self, path=None, horizon_seconds=None, max_pending=5000, max_history=10000):
        state_root = "/data" if os.path.isdir("/data") else "."
        self.path = path or os.getenv(
            "AGENT_LEARNING_FILE",
            os.path.join(state_root, "agent_learning.json"),
        )
        self.horizon_seconds = int(
            horizon_seconds
            if horizon_seconds is not None
            else os.getenv("AGENT_LEARNING_HORIZON_SECONDS", "300")
        )
        self.max_pending = max(100, int(max_pending))
        self.max_history = max(1000, int(max_history))
        Path(os.path.dirname(self.path) or ".").mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    def _load(self):
        default = {"pending": [], "history": [], "agents": {}}
        if not os.path.exists(self.path):
            return default
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict):
                return default
            for key in default:
                raw.setdefault(key, [])
            raw.setdefault("agents", {})
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

    def record_forecast(self, market_id, question, price, votes, confidence, edge, now=None):
        now = float(now if now is not None else time.time())
        directions = {
            agent: self._direction(vote)
            for agent, vote in (votes or {}).items()
            if self._direction(vote) != 0
        }
        if not directions:
            return
        self.data["pending"].append({
            "created_at": now,
            "resolve_after": now + self.horizon_seconds,
            "market_id": str(market_id),
            "question": question,
            "price": float(price),
            "edge": float(edge),
            "confidence": float(confidence),
            "directions": directions,
        })
        self.data["pending"] = self.data["pending"][-self.max_pending:]
        self._save()

    def _record_agent(self, agent, direction, outcome):
        d = self.data["agents"].setdefault(agent, {
            "forecasts": 0,
            "correct": 0,
            "incorrect": 0,
            "brier_sum": 0.0,
            "last_updated": None,
        })
        d["forecasts"] += 1
        correct = direction == outcome
        d["correct"] += int(correct)
        d["incorrect"] += int(not correct)
        # Directional confidence is intentionally capped. This score is for
        # weighting debate influence, not for treating confidence as truth.
        p = 0.5 + 0.5 * min(0.95, max(0.0, abs(direction)))
        d["brier_sum"] += (p - (1.0 if correct else 0.0)) ** 2
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
                if abs(current - previous) < float(os.getenv("LEARNING_MIN_MOVE", "0.001")):
                    # No directional outcome yet; retry once on a later cycle.
                    item["resolve_after"] = now + self.horizon_seconds
                    remaining.append(item)
                    continue
                outcome = 1 if current > previous else -1
                for agent, direction in item.get("directions", {}).items():
                    self._record_agent(agent, direction, outcome)
                item["resolved_at"] = now
                item["outcome"] = outcome
                item["resolved_price"] = current
                self.data["history"].append(item)
                resolved += 1
            except Exception:
                remaining.append(item)
        self.data["pending"] = remaining[-self.max_pending:]
        self.data["history"] = self.data["history"][-self.max_history:]
        if resolved:
            self._save()
        return resolved

    def stats(self, agent):
        d = self.data["agents"].get(agent, {})
        n = int(d.get("forecasts", 0))
        return {
            "forecasts": n,
            "accuracy": (d.get("correct", 0) / n) if n else None,
            "brier": (d.get("brier_sum", 0.0) / n) if n else None,
        }

    def weight(self, agent, minimum_samples=20):
        stats = self.stats(agent)
        n = stats["forecasts"]
        if n < minimum_samples:
            return 1.0
        accuracy = float(stats["accuracy"])
        # Small bounded influence adjustment; no agent can dominate.
        return max(0.70, min(1.30, 1.0 + (accuracy - 0.50) * 1.2))

    def summary(self):
        return {
            "pending": len(self.data["pending"]),
            "resolved": len(self.data["history"]),
            "agents": {
                agent: self.stats(agent)
                for agent in sorted(self.data["agents"])
            },
        }
