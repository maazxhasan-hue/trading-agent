"""Durable 3-hour GEN controller for the MCX paper tournament.

The controller manages generation lifecycle only. It does not create signals,
call a broker, deploy code, or enable live orders. It selects only generations
created for this run and reports NO_QUALIFIED_CHAMPION when none pass the ledger.
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
    """Maintain a fixed active population, lineage, deadline and durable result."""

    def __init__(
        self,
        ledger,
        state_path="data/mcx_gen_evolution.json",
        population_size=5,
        tournament_seconds=10800,
        target_hourly_net_pnl=1000.0,
        portfolios=None,
        clock=_utc,
    ):
        self.ledger = ledger
        self.portfolios = portfolios
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
            if isinstance(value, dict) and value.get("started_at") and isinstance(value.get("session_generations"), list):
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
            "session_generations": sorted(\n                int(key) for key, record in self.ledger.state.get("generations", {}).items()\n                if record.get("stage") == "GEN_TOURNAMENT" and record.get("status") == "ACTIVE"\n            ),
            "status": "RUNNING",
            "champion_generation": None,
            "result": None,
            "replacement_history": [],
            "champion_history": [],
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
        session_ids = {int(value) for value in self.state["session_generations"]}
        return sorted(
            int(key) for key, record in self._records().items()
            if int(key) in session_ids
            and record.get("stage") == "GEN_TOURNAMENT"
            and record.get("status") == "ACTIVE"
        )

    def _new_generation(self, parent_generation=None):
        generation = max((int(key) for key in self._records()), default=0) + 1
        record = self.ledger.ensure_generation(generation, parent_generation=parent_generation)
        self.state["session_generations"].append(generation)
        if self.portfolios is not None:
            self.portfolios.ensure_generation(generation)
        self.state["replacement_history"].append({
            "generation": generation,
            "parent_generation": parent_generation,
            "created_at": self.clock().isoformat(),
            "reason": "initial_population" if parent_generation is None else "replacement",
        })
        self._save()
        return record

    def replenish(self):
        """Replace retired agents while running; only this run's population counts."""
        if self.state.get("status") not in {"RUNNING", "CHAMPION_RUNNING"}:
            return self.active_generations()
        active = self.active_generations()
        session_ids = {int(value) for value in self.state["session_generations"]}
        retired = sorted(
            int(key) for key, rec in self._records().items()
            if int(key) in session_ids and rec.get("status") == "RETIRED" and rec.get("stage") == "RETIRED"
        )
        parent = retired[-1] if retired else None
        while len(active) < self.population_size:
            record = self._new_generation(parent_generation=parent)
            active.append(int(record["generation"]))
            parent = int(record["generation"])
        return sorted(active)

    def _select_session_champion(self, now):
        candidates = []
        for generation in self.state["session_generations"]:
            record = self._records().get(str(int(generation)))
            if not record or record.get("stage") != "GEN_TOURNAMENT":
                continue
            card = self.ledger.scorecard(int(generation), now=now)
            if card.get("promotion_eligible"):
                candidates.append((
                    float(card["net_pnl"]),
                    -float(card["max_drawdown_fraction"]),
                    int(card["trades"]),
                    int(generation),
                    card,
                ))
        if not candidates:
            return None
        _, _, _, winner, card = max(candidates)
        # Selection here means a paper champion only. Angel One validation is
        # intentionally not scheduled by the evolution controller.
        record = self._records()[str(winner)]
        record["status"] = "ACTIVE"
        record["stage"] = "GEN_TOURNAMENT"
        self.ledger.state["champion_generation"] = winner
        save = getattr(self.ledger, "_save", None)
        if callable(save):
            save()
        return {"generation": winner, "scorecard": card, "next_stage": "CONTINUOUS_PAPER", "status": "SELECTED"}

    def tick(self):
        """Advance lifecycle; Angel One validation and live orders remain disabled."""
        now = self.clock()
        if self.state.get("status") == "CHAMPION_RUNNING":
            champion_id = self.state.get("champion_generation")
            champion_record = self._records().get(str(champion_id)) if champion_id is not None else None
            if not champion_record or champion_record.get("status") != "ACTIVE":
                # Champion failed the user's loss-elimination rule. Start a new
                # bounded paper evolution session; never jump directly to live.
                self.state["champion_history"].append({
                    "generation": champion_id,
                    "ended_at": now.isoformat(),
                    "reason": "champion_retired_or_inactive",
                })
                self.state.update({
                    "started_at": now.isoformat(),
                    "deadline_at": (now + timedelta(seconds=self.tournament_seconds)).isoformat(),
                    "session_generations": [],
                    "status": "RUNNING",
                    "champion_generation": None,
                    "result": None,
                })
                self._save()
        if self.state.get("status") == "RUNNING":
            self.replenish()
            deadline = _utc(self.state["deadline_at"])
            if now >= deadline:
                champion = self._select_session_champion(now)
                if champion:
                    winner = int(champion["generation"])
                    # Keep only the winner active in the paper bridge after the
                    # selection deadline; validation/live execution stay separate.
                    for generation in self.state["session_generations"]:
                        record = self._records().get(str(int(generation)))
                        if not record or int(generation) == winner:
                            continue
                        if record.get("status") == "ACTIVE":
                            record["status"] = "RETIRED"
                            record["stage"] = "RETIRED"
                            record["retirement_reason"] = "not_selected_as_champion"
                    winning_record = self._records()[str(winner)]
                    winning_record["status"] = "ACTIVE"
                    winning_record["stage"] = "GEN_TOURNAMENT"
                    self.state["status"] = "CHAMPION_RUNNING"
                    self.state["champion_generation"] = winner
                    self.state["result"] = champion
                    self.state["champion_history"].append({
                        "generation": winner,
                        "selected_at": now.isoformat(),
                        "status": "paper_champion_running",
                    })
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
            "session_generations": list(self.state["session_generations"]),
            "champion_generation": self.state.get("champion_generation"),
            "result": self.state.get("result"),
            "live_orders_enabled": False,
            "angelone_validation_started": False,
            "continuous_paper_champion": self.state.get("status") == "CHAMPION_RUNNING",
        }
