import unittest
from unittest.mock import patch

import research_pipeline


class FakeMarket:
    def __init__(self, market_id, question, yes_price):
        self.id = market_id
        self.question = question
        self.yes_price = yes_price
        self.yes_token = "token-" + market_id


class ResearchPipelineTests(unittest.TestCase):
    def test_research_reports_source_coverage(self):
        market = FakeMarket("1", "Will bitcoin rise tomorrow?", 0.55)
        with patch.object(
            research_pipeline,
            "price_history",
            return_value=[{"p": 0.50 + i * 0.01} for i in range(8)],
        ), patch.object(
            research_pipeline,
            "_book",
            return_value=(0.10, 100.0, 0.0),
        ), patch.object(
            research_pipeline,
            "_news",
            return_value=(0.70, []),
        ), patch.object(
            research_pipeline,
            "_macro_event",
            return_value=(0.60, [research_pipeline.ResearchEvidence("macro", "macro", "macro", 0.8)]),
        ), patch.object(
            research_pipeline,
            "_crypto",
            return_value=(0.20, "ok"),
        ), patch.object(
            research_pipeline,
            "_social",
            return_value=(0.0, "unavailable_no_token"),
        ):
            snapshot = research_pipeline.research_market(market, [market])
        self.assertIn("market_history", snapshot.source_status)
        self.assertTrue(snapshot.source_status["market_history"])
        self.assertTrue(snapshot.source_status["order_book"])
        self.assertTrue(snapshot.source_status["crypto"])
        self.assertFalse(snapshot.source_status["x_social"])
        self.assertTrue(snapshot.research_complete)
        self.assertEqual(snapshot.source_failures, [])

    def test_cross_market_uses_market_id_field(self):
        market = FakeMarket("1", "Will bitcoin rise tomorrow?", 0.55)
        peer = FakeMarket("2", "Will bitcoin rise next week?", 0.65)
        with patch.object(
            research_pipeline,
            "price_history",
            return_value=[{"p": 0.50 + i * 0.01} for i in range(8)],
        ), patch.object(
            research_pipeline,
            "_book",
            return_value=(0.10, 100.0, 0.0),
        ), patch.object(
            research_pipeline,
            "_news",
            return_value=(0.70, []),
        ), patch.object(
            research_pipeline,
            "_macro_event",
            return_value=(0.60, []),
        ), patch.object(
            research_pipeline,
            "_crypto",
            return_value=(0.20, "ok"),
        ), patch.object(
            research_pipeline,
            "_social",
            return_value=(0.0, "unavailable_no_token"),
        ):
            snapshot = research_pipeline.research_market(market, [market, peer])

        self.assertGreater(snapshot.cross_market_score, 0.0)
        self.assertGreaterEqual(snapshot.fair_value, 0.01)
        self.assertLessEqual(snapshot.fair_value, 0.99)
        self.assertGreaterEqual(snapshot.confidence, 0.50)
        self.assertLessEqual(snapshot.confidence, 0.95)

    def test_incomplete_required_source_blocks_research(self):
        market = FakeMarket("1", "Will bitcoin rise tomorrow?", 0.55)
        with patch.object(research_pipeline, "price_history", return_value=[]), \
             patch.object(research_pipeline, "_book", return_value=(0.10, 100.0, 0.0)), \
             patch.object(research_pipeline, "_news", return_value=(0.70, [])), \
             patch.object(research_pipeline, "_macro_event", return_value=(0.60, [])), \
             patch.object(research_pipeline, "_crypto", return_value=(0.20, "ok")), \
             patch.object(research_pipeline, "_social", return_value=(0.0, "unavailable_no_token")):
            snapshot = research_pipeline.research_market(market, [market])
        self.assertFalse(snapshot.research_complete)
        self.assertIn("market_history", snapshot.source_failures)


if __name__ == "__main__":
    unittest.main()
