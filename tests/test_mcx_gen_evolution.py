"""Unit tests for the durable GEN evolution controller."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from mcx_gen_evolution import MCXGenEvolutionController


class FakeLedger:
    def __init__(self):
        self.window_seconds = 3600
        self.state = {"generations": {}, "promotions": [], "champion_generation": None}
        self.eligible = {}
    def ensure_generation(self, generation, parent_generation=None):
        key = str(int(generation))
        self.state["generations"].setdefault(key, {
            "generation": int(generation), "parent_generation": parent_generation,
            "stage": "GEN_TOURNAMENT", "status": "ACTIVE", "trades": [],
        })
        return self.state["generations"][key]
    def scorecard(self, generation, now=None):
        return self.eligible.get(int(generation), {
            "promotion_eligible": False, "net_pnl": 0, "max_drawdown_fraction": 0, "trades": 0,
        })


class GenEvolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        self.ledger = FakeLedger()
        self.path = os.path.join(self.tmp.name, "controller.json")
        self.controller = MCXGenEvolutionController(
            self.ledger, state_path=self.path, population_size=2,
            tournament_seconds=10800, clock=lambda: self.now,
        )

    def test_creates_population_and_persists_session_ids(self):
        state = self.controller.tick()
        self.assertEqual(len(state["active_generations"]), 2)
        self.assertEqual(len(state["session_generations"]), 2)
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

    def test_deadline_selects_best_qualified_generation_in_this_session(self):
        self.ledger.eligible[1] = {"promotion_eligible": True, "net_pnl": 1000.0, "max_drawdown_fraction": 0.05, "trades": 3}
        self.ledger.eligible[2] = {"promotion_eligible": True, "net_pnl": 1100.0, "max_drawdown_fraction": 0.04, "trades": 4}
        self.now += timedelta(hours=3)
        state = self.controller.tick()
        self.assertEqual(state["status"], "CHAMPION_SELECTED")
        self.assertEqual(state["champion_generation"], 2)
        self.assertFalse(state["live_orders_enabled"])
        self.assertEqual(self.ledger.state["generations"]["2"]["status"], "PROMOTION_PENDING")

    def test_old_generations_are_not_part_of_new_session(self):
        self.ledger.ensure_generation(99)
        self.controller.replenish()
        self.ledger.eligible[99] = {"promotion_eligible": True, "net_pnl": 5000.0, "max_drawdown_fraction": 0.0, "trades": 10}
        self.now += timedelta(hours=3)
        state = self.controller.tick()
        self.assertNotEqual(state["champion_generation"], 99)

    def test_restart_preserves_original_deadline_and_population(self):
        self.controller.replenish()
        deadline = self.controller.state["deadline_at"]
        ids = list(self.controller.state["session_generations"])
        restarted = MCXGenEvolutionController(
            self.ledger, state_path=self.path, population_size=2,
            tournament_seconds=10800, clock=lambda: self.now + timedelta(minutes=5),
        )
        self.assertEqual(restarted.state["deadline_at"], deadline)
        self.assertEqual(restarted.state["session_generations"], ids)


if __name__ == "__main__":
    unittest.main()
