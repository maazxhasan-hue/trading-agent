import unittest
from unittest.mock import patch
from agent_research_tools import AgentResearchTools

class ResearchToolsTests(unittest.TestCase):
    def test_rejects_non_http_urls(self):
        tools = AgentResearchTools()
        with self.assertRaises(ValueError):
            tools.fetch_page("news", "file:///etc/passwd")

    def test_browser_failure_is_reported(self):
        tools = AgentResearchTools()
        with patch.object(tools.manager, "browser_context", side_effect=RuntimeError("no browser")):
            result = tools.fetch_page("news", "https://example.com")
        self.assertFalse(result.ok)
        self.assertIn("no browser", result.error)

if __name__ == "__main__":
    unittest.main()
