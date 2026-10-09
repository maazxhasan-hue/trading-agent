"""Bounded GEN evolution controller for the MCX paper tournament.

This controller manages tournament generations only. It does not create trading
signals, call a broker, deploy code, or enable live orders. The 3-hour deadline
selects a champion only when the existing ledger's one-hour qualification rules
are satisfied; otherwise the result is explicitly NO_QUALIFIED_CHAMPION.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import tempfile


def _utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


class MCXGenEvolutionController:
    """Maintain a fixed-size population, lineage, deadline and durable result."""

    def __init__(
        self,
        ledger,
        state_path="data/mcx_gen_evolution.json",
        population_size=5,
        tournament_seconds=10800,
        target_hourly_net_pnl=1000.0,
        clock=_utc,
    ):
        self.ledger = ledger
        self.state_path = state_path
        self.population_size = max(1, int(population_size))
        self.tournament_seconds = int(tournament_seconds)
        self.target_hourly_net_pnl = float(target_hourly_net_pnl)
        if self.tournament_seconds <= 0:
            raise ValueError("tournament_seconds must be positive")
        if self.target_hourly_net_pnl <= 0:
            raise ValueError("target_hourly_net_pnl must be positive")
        self.clock = clock
        self.state = self._load()
        self._save()

    def _load(self):
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                value = json.load(handle)
            if isinstance(value, dict) and value.get("started_at"):
                return value
        except (OSError, ValueError, TypeError):
            pass
        now = self.clock()
        return {
            "started_at": now.isoformat(),
            "deadline_at": (now + timedelta(seconds=self.tournament_seconds)).isoformat(),
            "tournament_seconds": self.tournament_seconds,
            "population_size": self.population_size,
            "target_hourly_net_pnl": self.target_hourly_net_pnl,
            "status": "RUNNING",
            "champion_generation": None,
            "result": None,
            "replacement_history": [],
        }

    def _save(self):
        parent = os.path.dirname(self.state_path) or "."
        os.makedirs(parent, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".gen-evolution-", suffix=".tmp", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.state, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.state_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _records(self):
        return self.ledger.state.setdefault("generations", {})

    def active_generations(self):
        return sorted(
            int(key) for key, record in self._records().items()
            if record.get("stage") == "GEN_TOURNAMENT" and record.get("status") == "ACTIVE"
        )

    def _new_generation(self, parent_generation=None):
        generation = max((int(key) for key in self._records()), default=0) + 1
        record = self.ledger.ensure_generation(generation, parent_generation=parent_generation)
        self.state["replacement_history"].append({
            "generation": generation,
            "parent_generation": parent_generation,
            "created_at": self.clock().isoformat(),
            "reason": "initial_population" if parent_generation is None else "replacement",
        })
        self._save()
        return record

    def replenish(self):
        """Replace retired agents while running; never replace a qualified champion."""
        if self.state.get("status") != "RUNNING":
            return self.active_generations()
        active = self.active_generations()
        retired = sorted(
            (int(key), rec) for key, rec in self._records().items()
            if rec.get("status") == "RETIRED" and rec.get("stage") == "RETIRED"
        )
        parent = retired[-1][0] if retired else None
        while len(active) < self.population_size:
            record = self._new_generation(parent_generation=parent)
            active.append(int(record["generation"]))
            parent = int(record["generation"])
        return sorted(active)

    def tick(self):
        """Advance the controller and return a dashboard-safe status snapshot."""
        now = self.clock()
        if self.state.get("status") == "RUNNING":
            self.replenish()
            deadline = _utc(self.state["deadline_at"])
            if now >= deadline:
                champion = self.ledger.select_champion(now=now)
                if champion:
                    self.state["status"] = "CHAMPION_SELECTED"
                    self.state["champion_generation"] = int(champion["generation"])
                    self.state["result"] = champion
                else:
                    self.state["status"] = "NO_QUALIFIED_CHAMPION"
                    self.state["result"] = {
                        "reason": "no_generation_passed_all_qualification_gates",
                        "required_hourly_net_pnl": self.target_hourly_net_pnl,
                        "window_seconds": getattr(self.ledger, "window_seconds", 3600),
                    }
                self.state["finished_at"] = now.isoformat()
                self._save()
        deadline = _utc(self.state["deadline_at"])
        return {
            "status": self.state["status"],
            "started_at": self.state["started_at"],
            "deadline_at": self.state["deadline_at"],
            "seconds_remaining": max(0, int((deadline - now).total_seconds())),
            "active_generations": self.active_generations(),
            "champion_generation": self.state.get("champion_generation"),
            "result": self.state.get("result"),
            "live_orders_enabled": False,
            "angelone_validation_started": False,
        }
