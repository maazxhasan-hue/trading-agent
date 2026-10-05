import tempfile
import unittest

from agent_supervisor import AgentSupervisor


class SupervisorValidationTests(unittest.TestCase):
    def test_validation_is_safe_before_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            import os
            old_root = os.environ.get("AGENT_WORKSPACE_ROOT")
            old_learning = os.environ.get("AGENT_LEARNING_FILE")
            os.environ["AGENT_WORKSPACE_ROOT"] = tmp + "/workspaces"
            os.environ["AGENT_LEARNING_FILE"] = tmp + "/learning.json"
            try:
                supervisor = AgentSupervisor()
                result = supervisor.validation()
                self.assertEqual(result["status"], "collecting")
                self.assertEqual(result["qualified_count"], 0)
                self.assertEqual(result["required"], 3)
                self.assertFalse(result["live_trading_authorized"])
            finally:
                if old_root is None:
                    os.environ.pop("AGENT_WORKSPACE_ROOT", None)
                else:
                    os.environ["AGENT_WORKSPACE_ROOT"] = old_root
                if old_learning is None:
                    os.environ.pop("AGENT_LEARNING_FILE", None)
                else:
                    os.environ["AGENT_LEARNING_FILE"] = old_learning


if __name__ == "__main__":
    unittest.main()
