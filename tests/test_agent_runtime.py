import unittest
from tempfile import TemporaryDirectory
from agent_runtime import AgentRuntimeManager

class AgentRuntimeTests(unittest.TestCase):
    def test_agents_get_isolated_workspaces_and_profiles(self):
        with TemporaryDirectory() as root:
            manager = AgentRuntimeManager(root)
            a = manager.provision("bull")
            b = manager.provision("bear")
            self.assertNotEqual(a.workspace, b.workspace)
            self.assertNotEqual(a.browser_profile, b.browser_profile)

    def test_allowlisted_terminal_command_runs(self):
        with TemporaryDirectory() as root:
            manager = AgentRuntimeManager(root)
            runtime = manager.provision("quant")
            result = manager.run_terminal(runtime, "python -c 'print(1)'")
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(result["stdout"].strip(), "1")

    def test_unsafe_commands_are_rejected(self):
        with TemporaryDirectory() as root:
            manager = AgentRuntimeManager(root)
            runtime = manager.provision("quant")
            with self.assertRaises(PermissionError):
                manager.run_terminal(runtime, "python -c 'print(1)' && whoami")
            with self.assertRaises(PermissionError):
                manager.run_terminal(runtime, "curl https://example.com")

    def test_agents_have_no_execution_access(self):
        with TemporaryDirectory() as root:
            manager = AgentRuntimeManager(root)
            status = manager.capability_status(manager.provision("risk"))
            self.assertFalse(status["order_execution_access"])

if __name__ == "__main__":
    unittest.main()
