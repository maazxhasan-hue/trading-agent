"""Unit tests for bounded GEN evolution lifecycle."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from mcx_gen_evolution import MCXGenEvolutionController


class FakeLedger:
    def __init__(self, path):
        self.path = path
        self.window_seconds = 3600
        self.state = {"generations": {}, "promotions": [], "champion_generation": None}
        self.next_champion = None

    def ensure_generation(self, generation, parent_generation=None):
        key = str(int(generation))
        self.state["generations"].setdefault(key, {
            "generation": int(generation), "parent_generation": parent_generation,
            "stage": "GEN_TOURNAMENT", "status": "ACTIVE", "trades": [],
        })
        self._save()
        return self.state["generations"][key]

    def _save(self):
        pass

    def select_champion(self, now=None):
        return self.next_champion


class GenEvolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        self.ledger = FakeLedger(self.tmp.name)
        self.controller = MCXGenEvolutionController(
            self.ledger,
            state_path=os.path.join(self.tmp.name, "controller.json"),
            population_size=2,
            tournament_seconds=10800,
            clock=lambda: self.now,
        )

    def test_creates_fixed_initial_population(self):
        state = self.controller.tick()
        self.assertEqual(len(state["active_generations"]), 2)
        self.assertEqual(state["status"], "RUNNING")
        self.assertFalse(state["live_orders_enabled"])

    def test_retires_and_replaces_agent_with_lineage(self):
        self.controller.replenish()
        self.ledger.state["generations"]["1"]["status"] = "RETIRED"
        self.ledger.state["generations"]["1"]["stage"] = "RETIRED"
        active = self.controller.replenish()
        self.assertEqual(len(active), 2)
        replacement = self.ledger.state["generations"]["3"]
        self.assertEqual(replacement["parent_generation"], 1)

    def test_deadline_without_qualified_champion_is_honest(self):
        self.now += timedelta(hours=3)
        state = self.controller.tick()
        self.assertEqual(state["status"], "NO_QUALIFIED_CHAMPION")
        self.assertIsNone(state["champion_generation"])
        self.assertFalse(state["angelone_validation_started"])

    def test_deadline_selects_only_ledger_qualified_champion(self):
        self.ledger.next_champion = {"generation": 2, "scorecard": {"net_pnl": 1000.0}}
        self.now += timedelta(hours=3)
        state = self.controller.tick()
        self.assertEqual(state["status"], "CHAMPION_SELECTED")
        self.assertEqual(state["champion_generation"], 2)
        self.assertFalse(state["live_orders_enabled"])

    def test_restart_preserves_original_deadline(self):
        deadline = self.controller.state["deadline_at"]
        restarted = MCXGenEvolutionController(
            self.ledger,
            state_path=os.path.join(self.tmp.name, "controller.json"),
            population_size=2,
            tournament_seconds=10800,
            clock=lambda: self.now + timedelta(minutes=5),
        )
        self.assertEqual(restarted.state["deadline_at"], deadline)


if __name__ == "__main__":
    unittest.main()
