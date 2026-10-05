import unittest
import tempfile
from agent_lifecycle import AgentLifecycleManager

class LifecycleTests(unittest.TestCase):
    def test_loss_quarantines_and_replacement_is_activated(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = AgentLifecycleManager(d + "/state.json")
            a = mgr.ensure("momentum-1", "momentum")
            mgr.register_outcome([a.agent_id], False, "fair_value_error")
            self.assertEqual(mgr.agents[a.agent_id].status, "ACTIVE")
            mgr.register_outcome([a.agent_id], False, "fair_value_error")
            self.assertEqual(mgr.agents[a.agent_id].status, "QUARANTINED")
            child = mgr.replace_after_loss([a.agent_id], "fair_value_error", 0.72)[0]
            self.assertEqual(child.status, "ACTIVE")
            self.assertNotEqual(child.agent_id, a.agent_id)

    def test_bad_replacement_is_not_activated(self):
        with tempfile.TemporaryDirectory() as d:
            mgr = AgentLifecycleManager(d + "/state.json")
            a = mgr.ensure("mean-1", "mean_reversion")
            mgr.register_outcome([a.agent_id], False, "regime_shift")
            self.assertEqual(mgr.replace_after_loss([a.agent_id], "regime_shift", 0.40), [])

if __name__ == "__main__":
    unittest.main()
