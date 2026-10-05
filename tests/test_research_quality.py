import unittest, time
from research_quality import ResearchQuality

class ResearchQualityTests(unittest.TestCase):
    def test_fresh_source_is_usable(self):
        q = ResearchQuality()
        self.assertTrue(q.add("news", True, time.time(), 2, max_age=60))
        self.assertTrue(q.complete)
        self.assertTrue(q.status()["news"])

    def test_stale_source_fails(self):
        q = ResearchQuality()
        self.assertFalse(q.add("news", True, time.time() - 120, 1, max_age=60))
        self.assertFalse(q.complete)
        self.assertIn("news", q.failures)

if __name__ == "__main__":
    unittest.main()
