import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import market_data


class MarketFeedTests(unittest.TestCase):
    def test_parse_rejects_invalid_market_and_keeps_valid(self):
        rows = [
            {"id":"bad","question":"bad","outcomePrices":"[0.5]","clobTokenIds":"[]"},
            {"id":"ok","question":"good","outcomePrices":"[0.6,0.4]",
             "clobTokenIds":"[\"yes\",\"no\"]","volume":"12","liquidity":"5"},
        ]
        parsed = market_data._parse(rows)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].id, "ok")

    def test_cache_fallback_is_marked_stale(self):
        rows = [{"id":"ok","question":"good","outcomePrices":"[0.6,0.4]",
                 "clobTokenIds":"[\"yes\",\"no\"]","volume":"12","liquidity":"5"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp + "/cache.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"cached_at":"2099-01-01T00:00:00+00:00","markets":rows}, f)
            old_path = market_data._cache_path
            old_age = market_data._cache_max_age
            old_stale, old_status = market_data.LAST_FEED_STALE, market_data.LAST_FEED_STATUS
            market_data._cache_path = lambda: path
            market_data._cache_max_age = lambda: 3600
            market_data.LAST_FEED_STALE = False
            market_data.LAST_FEED_STATUS = "unknown"
            try:
                with patch.object(market_data, "_request_page", return_value=(None, "rate_limited")):
                    parsed = market_data.markets(10)
                self.assertEqual(len(parsed), 1)
                self.assertTrue(market_data.LAST_FEED_STALE)
                self.assertEqual(market_data.LAST_FEED_STATUS, "rate_limited_cache")
            finally:
                market_data._cache_path = old_path
                market_data._cache_max_age = old_age
                market_data.LAST_FEED_STALE, market_data.LAST_FEED_STATUS = old_stale, old_status

    def test_keyset_cursor_paginates_without_duplicate_cursor(self):
        pages = [
            ({"markets":[{"id":"1","question":"a","outcomePrices":"[0.6,0.4]",
                          "clobTokenIds":"[\"y\",\"n\"]","volume":1,"liquidity":1}],
              "next_cursor":"c1"}, "ok"),
            ({"markets":[{"id":"2","question":"b","outcomePrices":"[0.7,0.3]",
                          "clobTokenIds":"[\"y2\",\"n2\"]","volume":2,"liquidity":1}],
              "next_cursor":"c2"}, "ok"),
        ]
        with patch.object(market_data, "_request_page", side_effect=pages):
            parsed = market_data.markets(2)
        self.assertEqual([m.id for m in parsed], ["2","1"])


if __name__ == "__main__":
    unittest.main()
