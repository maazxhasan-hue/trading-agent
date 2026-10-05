import tempfile
import unittest
from agent_runtime import AgentRuntimeManager

class RuntimeTests(unittest.TestCase):
    def test_private_workspaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=AgentRuntimeManager(tmp)
            a=m.provision("momentum")
            b=m.provision("bear")
            self.assertNotEqual(a.workspace,b.workspace)
            self.assertNotEqual(a.browser_profile,b.browser_profile)
            self.assertTrue(a.browser_profile.exists())
            self.assertEqual(a, m.provision("momentum"))
            status = m.capability_status(a)
            self.assertTrue(status["browser_enabled"])
            self.assertTrue(status["terminal_enabled"])

    def test_compound_commands_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            m=AgentRuntimeManager(tmp)
            with self.assertRaises(PermissionError):
                m.run_terminal(m.provision("quant"), "python -V && whoami")

if __name__=="__main__":
    unittest.main()
