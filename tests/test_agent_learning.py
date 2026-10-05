import tempfile
import unittest

from agent_learning import AgentLearningStore


class AgentLearningTests(unittest.TestCase):
    def test_forecast_resolves_and_updates_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp + "/learning.json"
            store = AgentLearningStore(path=path, horizon_seconds=0)
            prices = {"m1": 0.60}
            store.record_forecast(
                "m1", "test", 0.50,
                {"momentum-v1": 1.0, "bear-v1": -1.0},
                0.85, 0.10, now=1.0,
            )
            resolved = store.resolve(lambda market_id: prices.get(market_id), now=2.0)
            self.assertEqual(resolved, 1)
            self.assertEqual(store.stats("momentum-v1")["accuracy"], 1.0)
            self.assertEqual(store.stats("bear-v1")["accuracy"], 0.0)

    def test_small_edge_forecast_is_recorded_by_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AgentLearningStore(path=tmp + "/learning.json", horizon_seconds=0)
            store.record_forecast(
                "m1", "test", 0.500,
                {"momentum-v1": 1.0}, 0.85, 0.005, now=1.0,
            )
            self.assertEqual(len(store.data["pending"]), 1)

    def test_market_observations_build_persistent_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AgentLearningStore(path=tmp + "/learning.json", horizon_seconds=0)
            for i in range(3):
                store.record_observation("m1", 0.50 + i * 0.01, now=float(i), save=False)
            store._save()
            self.assertEqual(store.history_for_market("m1"), [0.50, 0.51, 0.52])

    def test_qualification_requires_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AgentLearningStore(path=tmp + "/learning.json")
            ok, reason, stats = store.qualification("new-agent")
            self.assertFalse(ok)
            self.assertEqual(reason, "insufficient_samples")
            self.assertEqual(stats["forecasts"], 0)

            store.data["agents"]["trained-agent"] = {
                "forecasts": 30,
                "correct": 20,
                "incorrect": 10,
                "brier_sum": 4.0,
                "last_updated": 1.0,
            }
            ok, reason, stats = store.qualification("trained-agent")
            self.assertTrue(ok)
            self.assertEqual(reason, "validated")
            self.assertAlmostEqual(stats["accuracy"], 20 / 30)

    def test_qualified_agents_reports_unqualified_and_qualified(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AgentLearningStore(path=tmp + "/learning.json")
            store.data["agents"]["good"] = {
                "forecasts": 30, "correct": 20, "incorrect": 10,
                "brier_sum": 4.0, "last_updated": 1.0,
            }
            qualified, details = store.qualified_agents(["good", "new"])
            self.assertEqual(qualified, ["good"])
            self.assertTrue(details["good"]["qualified"])
            self.assertEqual(details["new"]["reason"], "insufficient_samples")

    def test_observation_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AgentLearningStore(path=tmp + "/learning.json")
            store.record_observation("m1", 0.50, save=False)
            store.record_observation("m1", 0.51, save=False)
            store.record_observation("m2", 0.40, save=False)
            self.assertEqual(store.observation_count(), 3)

    def test_weight_waits_for_sample_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AgentLearningStore(path=tmp + "/learning.json", horizon_seconds=0)
            self.assertEqual(store.weight("new-agent"), 1.0)

    def test_weight_changes_after_enough_observations(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AgentLearningStore(path=tmp + "/learning.json", horizon_seconds=0)
            for i in range(30):
                store.record_forecast(
                    "m" + str(i), "test", 0.50,
                    {"momentum-v1": 1.0}, 0.80, 0.10, now=float(i)
                )
            store.resolve(lambda market_id: 0.60, now=100.0)
            self.assertGreater(store.weight("momentum-v1"), 1.0)


if __name__ == "__main__":
    unittest.main()
