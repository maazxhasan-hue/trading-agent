import unittest
from nse_debate import NSEPreTradeDebate

class DebateTests(unittest.TestCase):
    def setUp(self):
        self.d = NSEPreTradeDebate(min_agreement=0.60, max_conflict=0.45)

    def test_consensus_buy(self):
        result = self.d.run(
            {"r5":0.01,"r20":0.02,"breakout":0.01,"volume_ratio":1.8,"reversion":0.0},
            {"a":0.8,"b":0.7,"c":0.9,"d":0.6},
            ["a","b","c","d"],
        )
        self.assertEqual(result.decision, "BUY")
        self.assertEqual(result.direction, 1)

    def test_conflict_is_no_trade(self):
        result = self.d.run(
            {"r5":0.0,"r20":0.0,"breakout":0.0,"volume_ratio":1.0,"reversion":0.0},
            {"a":0.8,"b":0.7,"c":-0.9,"d":-0.8},
            ["a","b","c","d"],
        )
        self.assertEqual(result.decision, "NO_TRADE")

    def test_insufficient_agents(self):
        result = self.d.run({}, {"a":0.8,"b":0.7}, ["a","b"])
        self.assertEqual(result.decision, "NO_TRADE")

    def test_overbought_long_is_vetoed(self):
        result = self.d.run(
            {"r5":0.02,"r20":0.03,"breakout":0.02,"volume_ratio":1.3,
             "range_ratio":1.1,"trend_gap":0.02,"rsi":85},
            {"a":0.9,"b":0.8,"c":0.7}, ["a","b","c"],
        )
        self.assertEqual(result.decision, "NO_TRADE")
        self.assertIn("overbought", result.rationale)

    def test_context_weighting_keeps_specialists_auditable(self):
        result = self.d.run(
            {"r3":0.02,"r5":0.03,"r10":0.04,"r20":0.05,"trend_gap":0.03,
             "reversion":0.0,"breakout":0.02,"volume_ratio":1.5,
             "range_ratio":1.1,"rsi":62},
            {"momentum-v3":0.9,"mean_reversion-v3":-0.8,
             "event_driven-v3":0.7,"mcx_commodity_specialist-v3":0.6,
             "cross_market_arbitrage-v3":0.6},
            ["momentum-v3","mean_reversion-v3","event_driven-v3",
             "mcx_commodity_specialist-v3","cross_market_arbitrage-v3"],
        )
        self.assertEqual(result.decision, "BUY")
        self.assertGreater(result.score, 0.0)

    def test_learning_weight_changes_influence(self):
        result = self.d.run(
            {"r5":0.01,"r20":0.01,"breakout":0.01,"volume_ratio":1.2,
             "range_ratio":1.1,"trend_gap":0.0,"rsi":55},
            {"momentum-v3":0.9,"mean_reversion-v3":0.8,"event_driven-v3":0.7},
            ["momentum-v3","mean_reversion-v3","event_driven-v3"],
            {"momentum-v3":1.3,"mean_reversion-v3":0.7,"event_driven-v3":1.0},
        )
        self.assertEqual(result.decision, "BUY")

if __name__ == "__main__":
    unittest.main()
