import tempfile
import unittest

from agent_lifecycle import AgentLifecycleManager


class AgentLifecycleTests(unittest.TestCase):
    def test_one_loss_quarantines_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = AgentLifecycleManager(path=tmp + "/lifecycle.json")
            mgr.ensure("momentum-v1", "momentum")
            mgr.register_outcome(["momentum-v1"], False, "thesis_failure")
            self.assertEqual(mgr.agents["momentum-v1"].status, "QUARANTINED")
            self.assertEqual(mgr.agents["momentum-v1"].rule_violations, 1)

    def test_replacement_requires_validation_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = AgentLifecycleManager(path=tmp + "/lifecycle.json")
            mgr.ensure("momentum-v1", "momentum")
            child = mgr.evolve_replacement("momentum-v1", "loss_autopsy", validation_score=0.40)
            self.assertIsNone(child)
            self.assertEqual(mgr.agents["momentum-v1"].status, "ACTIVE")

    def test_win_does_not_add_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = AgentLifecycleManager(path=tmp + "/lifecycle.json")
            mgr.ensure("momentum-v1", "momentum")
            mgr.register_outcome(["momentum-v1"], True)
            self.assertEqual(mgr.agents["momentum-v1"].wins, 1)
            self.assertEqual(mgr.agents["momentum-v1"].rule_violations, 0)


if __name__ == "__main__":
    unittest.main()
