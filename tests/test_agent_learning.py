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

    def test_weight_waits_for_sample_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AgentLearningStore(path=tmp + "/learning.json", horizon_seconds=0)
            self.assertEqual(store.weight("new-agent"), 1.0)


if __name__ == "__main__":
    unittest.main()
