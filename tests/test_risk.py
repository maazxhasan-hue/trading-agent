import unittest
from portfolio_risk import PortfolioRisk,Position
class RiskTests(unittest.TestCase):
    def test_position_cap(self):
        ok,reason=PortfolioRisk().approve(.07,[],0)
        self.assertFalse(ok); self.assertEqual(reason,"position_cap")
    def test_daily_loss(self):
        ok,reason=PortfolioRisk().approve(.03,[], -.04)
        self.assertFalse(ok); self.assertEqual(reason,"daily_loss_limit")
if __name__=="__main__":unittest.main()
