import unittest
import agent
class ImportTests(unittest.TestCase):
    def test_company_constructs(self):
        bot=agent.TradingCompany()
        self.assertIsNotNone(bot.feed)
        self.assertEqual(bot.risk is not None, True)
if __name__=="__main__": unittest.main()
