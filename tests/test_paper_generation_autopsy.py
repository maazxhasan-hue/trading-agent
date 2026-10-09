import unittest
from types import SimpleNamespace
from unittest.mock import patch

from nse_agent import NSETradingCompany


class FakeJournal:
    def __init__(self):
        self.records = []

    def record(self, event, **payload):
        self.records.append((event, payload))


class PaperGenerationAutopsyTests(unittest.TestCase):
    def test_one_losing_trade_retires_generation_and_preserves_context(self):
        company = object.__new__(NSETradingCompany)
        company.execution = SimpleNamespace(enabled=False)
        company.paper_generation = 4
        company.paper_agent_alive = True
        company.paper_agent_knowledge = []
        company.paper_cycle = 9
        company.journal = FakeJournal()
        position = {
            "tradingsymbol": "GOLDM26OCTFUT",
            "side": "BUY",
            "entry": 100.0,
            "qty": 1,
            "stop_pct": 0.01,
            "score": 0.72,
            "confidence": 0.68,
            "features": {"rsi": 71.2, "vol": 0.02},
            "agent_votes": {"momentum-v3": 0.8, "mean_reversion-v3": -0.2},
        }
        with patch("nse_agent.hq_events.activity"), patch("nse_agent.hq_events.agent_analysis"), patch("nse_agent.hq_events.emit"):
            company._paper_agent_loss("token-1", -1.5, "stop", position, 98.5)
        self.assertEqual(company.paper_generation, 5)
        self.assertTrue(company.paper_agent_alive)
        self.assertEqual(len(company.paper_agent_knowledge), 1)
        lesson = company.paper_agent_knowledge[0]
        self.assertEqual(lesson["tradingsymbol"], "GOLDM26OCTFUT")
        self.assertEqual(lesson["exit_reason"], "stop")
        self.assertEqual(lesson["entry_features"]["rsi"], 71.2)
        self.assertEqual(lesson["agent_votes"]["momentum-v3"], 0.8)
        self.assertIn("not proof", lesson["lesson"])
        self.assertEqual(company.journal.records[-1][0], "PAPER_AGENT_REPLACEMENT")


if __name__ == "__main__":
    unittest.main()
