import unittest
from agent import Market, Proposal, ChiefDecisionAgent

class DebateTests(unittest.TestCase):
    def setUp(self):
        self.chief = ChiefDecisionAgent()
        self.market = Market("m1", "Test market", 0.40, 1000, 1000)

    def test_red_team_can_veto(self):
        p = Proposal(self.market, 0.52, 0.12, 0.90, "BUY_YES", 0.03,
                     {"a": 1.0, "b": 1.0}, "", ["a", "b"])
        decision, _, _ = self.chief.decide(
            p, [{"stance":"BUY_YES","argument":"x","strength":1}],
            ["no_liquidity"], 0.7)
        self.assertEqual(decision, "NO_TRADE")

    def test_chief_rejects_low_confidence_after_attack(self):
        p = Proposal(self.market, 0.52, 0.12, 0.81, "BUY_YES", 0.03,
                     {"a": 1.0, "b": 1.0}, "", ["a", "b"])
        decision, _, _ = self.chief.decide(
            p, [{"stance":"BUY_YES","argument":"x","strength":1}],
            ["external_evidence_unverified"], 0.9)
        self.assertEqual(decision, "NO_TRADE")

if __name__ == "__main__":
    unittest.main()
