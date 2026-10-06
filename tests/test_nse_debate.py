import unittest
from nse_debate import NSEPreTradeDebate

class DebateTests(unittest.TestCase):
    def setUp(self):
        self.d=NSEPreTradeDebate(min_agreement=0.60,max_conflict=0.45)

    def test_consensus_buy(self):
        result=self.d.run(
            {"r5":0.01,"r20":0.02,"breakout":0.01,"volume_ratio":1.8,"reversion":0.0},
            {"a":0.8,"b":0.7,"c":0.9,"d":0.6},
            ["a","b","c","d"],
        )
        self.assertEqual(result.decision,"BUY")
        self.assertEqual(result.direction,1)

    def test_conflict_is_no_trade(self):
        result=self.d.run(
            {"r5":0.0,"r20":0.0,"breakout":0.0,"volume_ratio":1.0,"reversion":0.0},
            {"a":0.8,"b":0.7,"c":-0.9,"d":-0.8},
            ["a","b","c","d"],
        )
        self.assertEqual(result.decision,"NO_TRADE")

    def test_insufficient_agents(self):
        result=self.d.run({},{"a":0.8,"b":0.7},["a","b"])
        self.assertEqual(result.decision,"NO_TRADE")

if __name__=="__main__":
    unittest.main()
