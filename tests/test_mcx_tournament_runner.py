import tempfile
import unittest
from pathlib import Path

from mcx_tournament import TournamentLedger
from mcx_tournament_runner import TournamentRunner


class TournamentRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.ledger = TournamentLedger(
            path=str(Path(self.temp_dir.name) / "tournament.json"),
            target_pnl=1000,
            window_seconds=3600,
            min_trades=3,
            max_drawdown_fraction=0.10,
        )
        self.runner = TournamentRunner(self.ledger, population_size=3)

    def test_initializes_population_and_keeps_live_orders_locked(self):
        state = self.runner.status()
        self.assertEqual(len(state["active_generations"]), 3)
        self.assertFalse(state["live_orders_enabled"])

    def test_evaluates_candidates_and_retires_on_first_loss(self):
        def evaluator(generation):
            if generation == 1:
                return [{"pnl": -1.0}, {"pnl": 100.0}]
            return []
        result = self.runner.evaluate_round(evaluator)
        record = self.ledger.state["generations"]["1"]
        self.assertEqual(record["status"], "RETIRED")
        self.assertEqual(len(record["trades"]), 1)
        self.assertFalse(result["live_orders_enabled"])
        self.assertEqual(len(result["active_generations"]), 3)

    def test_champion_requires_target_and_validation_never_enables_live(self):
        def evaluator(generation):
            if generation == 1:
                return [{"pnl": 400.0}, {"pnl": 350.0}, {"pnl": 300.0}]
            return []
        self.runner.evaluate_round(evaluator)
        promoted = self.runner.select_champion_for_validation()
        self.assertIsNotNone(promoted)
        generation = promoted["generation"]
        self.assertEqual(self.ledger.state["generations"][str(generation)]["status"], "VALIDATING")
        result = self.runner.complete_validation(generation, {
            "net_pnl": 120.0,
            "trades": 3,
            "duration_seconds": 3600,
            "max_drawdown_fraction": 0.02,
            "data_source": "angelone_mcx",
            "actual_contract_sizing": True,
        })
        self.assertTrue(result["passed"])
        self.assertFalse(result["live_orders_enabled"])
        self.assertTrue(result["requires_separate_operator_approval"])

    def test_missing_validation_evidence_is_rejected(self):
        self.runner.evaluate_round(lambda generation: [])
        with self.assertRaises(ValueError):
            self.runner.complete_validation(1, {"net_pnl": 10})


if __name__ == "__main__":
    unittest.main()
