import tempfile
import unittest

from agent_lifecycle import AgentLifecycleManager


class AgentLifecycleTests(unittest.TestCase):
    def test_loss_quarantines_after_two_violations(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = AgentLifecycleManager(path=tmp + "/lifecycle.json")
            mgr.ensure("momentum-v1", "momentum")
            mgr.register_outcome(["momentum-v1"], False, "thesis_failure")
            self.assertEqual(mgr.agents["momentum-v1"].status, "ACTIVE")
            self.assertEqual(mgr.agents["momentum-v1"].rule_violations, 1)
            mgr.register_outcome(["momentum-v1"], False, "thesis_failure")
            self.assertEqual(mgr.agents["momentum-v1"].status, "QUARANTINED")
            self.assertEqual(mgr.agents["momentum-v1"].rule_violations, 2)

    def test_win_does_not_add_violation(self):
        with tempfile.TemporaryDirectory() as tmp:
            mgr = AgentLifecycleManager(path=tmp + "/lifecycle.json")
            mgr.ensure("momentum-v1", "momentum")
            mgr.register_outcome(["momentum-v1"], True)
            self.assertEqual(mgr.agents["momentum-v1"].wins, 1)
            self.assertEqual(mgr.agents["momentum-v1"].rule_violations, 0)


if __name__ == "__main__":
    unittest.main()
