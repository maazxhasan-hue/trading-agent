"""Agent lifecycle manager: quarantine failed agents and evolve validated replacements.

A "kill" is a logical retirement/quarantine, not a destructive OS process kill.
Replacements must pass deterministic validation before activation.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import json, os
import hashlib


@dataclass
class AgentState:
    agent_id: str
    base_strategy: str
    version: int = 1
    status: str = "ACTIVE"
    wins: int = 0
    losses: int = 0
    rule_violations: int = 0
    fitness: float = 0.50
    last_failure: str = ""
    parent_id: str = ""


class AgentLifecycleManager:
    def __init__(self, path=None, calibration_floor=0.55):
        path = path or os.getenv("AGENT_LIFECYCLE_FILE", "agent_lifecycle.json")
        self.path = path
        self.calibration_floor = calibration_floor
        self.agents = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            return {k: AgentState(**v) for k, v in raw.items()}
        except Exception:
            return {}

    def _save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({k: asdict(v) for k, v in self.agents.items()}, f, indent=2)

    def ensure(self, agent_id, base_strategy):
        if agent_id not in self.agents:
            self.agents[agent_id] = AgentState(agent_id, base_strategy)
            self._save()
        return self.agents[agent_id]

    def active(self, base_strategy):
        return [a for a in self.agents.values()
                if a.base_strategy == base_strategy and a.status == "ACTIVE"]

    def register_outcome(self, agent_ids, won, failure_reason=""):
        for agent_id in agent_ids:
            a = self.agents.get(agent_id)
            if not a:
                continue
            if won:
                a.wins += 1
            else:
                a.losses += 1
                a.last_failure = failure_reason
            total = a.wins + a.losses
            a.fitness = a.wins / total if total else 0.50
            # A single verified losing thesis makes the specific agent ineligible
            # for the next decision; repeated failures cause full retirement.
            if not won:
                a.status = "QUARANTINED"
            self._save()

    def kill(self, agent_id, reason):
        a = self.agents.get(agent_id)
        if not a:
            return None
        a.status = "RETIRED"
        a.last_failure = reason
        self._save()
        return a

    def evolve_replacement(self, parent_id, mutation_reason, validation_score):
        parent = self.agents[parent_id]
        if validation_score < self.calibration_floor:
            return None
        digest = hashlib.sha1(
            f"{parent_id}:{parent.version}:{mutation_reason}".encode()
        ).hexdigest()[:8]
        new_id = f"{parent.base_strategy}.v{parent.version + 1}-{digest}"
        child = AgentState(
            agent_id=new_id,
            base_strategy=parent.base_strategy,
            version=parent.version + 1,
            status="ACTIVE",
            fitness=validation_score,
            parent_id=parent_id,
            last_failure="",
        )
        parent.status = "RETIRED"
        self.agents[new_id] = child
        self._save()
        return child

    def replace_after_loss(self, agent_ids, reason, validation_score):
        replacements = []
        for agent_id in agent_ids:
            a = self.agents.get(agent_id)
            if not a:
                continue
            a.status = "QUARANTINED"
            a.last_failure = reason
            child = self.evolve_replacement(agent_id, reason, validation_score)
            if child:
                replacements.append(child)
        self._save()
        return replacements
