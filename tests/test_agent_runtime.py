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
            self.assertTrue(a.workspace.exists())
            self.assertTrue(a.browser_profile.exists())

    def test_compound_shell_is_rejected(self):
        with TemporaryDirectory() as root:
            manager = AgentRuntimeManager(root)
            runtime = manager.provision("quant")
            with self.assertRaises(PermissionError):
                manager.run_terminal(runtime, "python -c 'print(1)' && whoami")


if __name__ == "__main__":
    unittest.main()
