import os
import tempfile
import unittest

from nse_regime import classify
from nse_risk import exposure_check, drawdown_check
from trade_journal import TradeJournal

class NSEComponentTests(unittest.TestCase):
    """Core production-stack smoke tests."""
    def test_regime_up(self):
        r=classify({"r5":0.01,"r20":0.02,"vol":0.005,"breakout":0.01,"volume_ratio":1.8})
        self.assertEqual(r.direction,1)

    def test_regime_down(self):
        r=classify({"r5":-0.01,"r20":-0.02,"vol":0.005,"breakout":-0.01,"volume_ratio":1})
        self.assertEqual(r.direction,-1)

    def test_exposure(self):
        self.assertTrue(exposure_check(100000,[],100,50).allowed)
        self.assertFalse(exposure_check(100000,[{"entry":200,"qty":100}],100,101).allowed)

    def test_drawdown(self):
        self.assertFalse(drawdown_check(89000,100000).allowed)
        self.assertTrue(drawdown_check(95000,100000).allowed)

    def test_journal(self):
        with tempfile.TemporaryDirectory() as d:
            p=os.path.join(d,"journal.jsonl")
            row=TradeJournal(p).record("SIGNAL",symbol="TEST",decision="NO_TRADE")
            self.assertEqual(row["event"],"SIGNAL")
            with open(p,encoding="utf-8") as f:
                self.assertIn("NO_TRADE",f.read())

if __name__=="__main__":
    unittest.main()
