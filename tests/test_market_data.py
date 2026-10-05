import json
import tempfile
import unittest
from unittest.mock import patch

import market_data


class MarketFeedTests(unittest.TestCase):
    def test_parse_rejects_invalid_market_and_keeps_valid(self):
        rows = [
            {"id":"bad","question":"bad","outcomePrices":"[0.5]","clobTokenIds":"[]"},
            {"id":"ok","question":"good","outcomePrices":"[0.6,0.4]","clobTokenIds":"[\"yes\",\"no\"]","volume":"12","liquidity":"5"},
        ]
        parsed = market_data._parse(rows)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].id, "ok")

    def test_cache_fallback_is_marked_stale(self):
        rows = [{"id":"ok","question":"good","outcomePrices":"[0.6,0.4]","clobTokenIds":"[\"yes\",\"no\"]","volume":"12","liquidity":"5"}]
        with tempfile.TemporaryDirectory() as tmp:
            path = tmp + "/cache.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"cached_at":"2099-01-01T00:00:00+00:00","markets":rows}, f)
            old_path, old_age = market_data._cache_path, market_data._cache_max_age
            old_stale, old_status = market_data.LAST_FEED_STALE, market_data.LAST_FEED_STATUS
            market_data._cache_path = lambda: path
            market_data._cache_max_age = lambda: 3600
            try:
                with patch.object(market_data, "_request_page", return_value=(None, "rate_limited")):
                    parsed = market_data.markets(10)
                self.assertEqual(len(parsed), 1)
                self.assertTrue(market_data.LAST_FEED_STALE)
                self.assertEqual(market_data.LAST_FEED_STATUS, "rate_limited_cache")
            finally:
                market_data._cache_path, market_data._cache_max_age = old_path, old_age
                market_data.LAST_FEED_STALE, market_data.LAST_FEED_STATUS = old_stale, old_status

    def test_rate_limit_enters_cooldown_after_retries(self):
        class FakeResponse:
            status_code = 429
            headers = {}
            def raise_for_status(self):
                raise RuntimeError("429")
        calls = []
        old_until = market_data.GAMMA_RATE_LIMIT_UNTIL
        try:
            with patch.dict(
                "os.environ",
                {
                    "GAMMA_REQUEST_RETRIES": "1",
                    "GAMMA_MIN_REQUEST_INTERVAL_SECONDS": "0",
                    "GAMMA_BACKOFF_BASE_SECONDS": "0.01",
                    "GAMMA_MAX_RETRY_WAIT_SECONDS": "0.01",
                    "GAMMA_RATE_LIMIT_COOLDOWN_SECONDS": "60",
                },
                clear=False,
            ), patch.object(
                market_data.S,
                "get",
                side_effect=lambda *args, **kwargs: calls.append(1) or FakeResponse(),
            ), patch.object(market_data.time, "sleep"):
                payload, status = market_data._request_page({"limit": 1})
                self.assertIsNone(payload)
                self.assertEqual(status, "rate_limited")
                self.assertEqual(len(calls), 2)
                payload, status = market_data._request_page({"limit": 1})
                self.assertIsNone(payload)
                self.assertEqual(status, "rate_limited_cooldown")
                self.assertEqual(len(calls), 2)
        finally:
            market_data.GAMMA_RATE_LIMIT_UNTIL = old_until

    def test_keyset_cursor_paginates(self):
        pages = [
            ({"markets":[{"id":"1","question":"a","outcomePrices":"[0.6,0.4]","clobTokenIds":"[\"y\",\"n\"]","volume":1,"liquidity":1}],"next_cursor":"c1"}, "ok"),
            ({"markets":[{"id":"2","question":"b","outcomePrices":"[0.7,0.3]","clobTokenIds":"[\"y2\",\"n2\"]","volume":2,"liquidity":1}],"next_cursor":"c2"}, "ok"),
        ]
        with patch.object(market_data, "_request_page", side_effect=pages):
            parsed = market_data.markets(2)
        self.assertEqual([m.id for m in parsed], ["2","1"])


if __name__ == "__main__":
    unittest.main()
