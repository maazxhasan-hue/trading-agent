import json
import os
import tempfile
import unittest
from unittest.mock import patch

import market_data


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError("status=%s" % self.status_code)

    def json(self):
        return self._payload


def row(volume="100"):
    return {
        "id": "m1",
        "question": "Test market",
        "outcomePrices": json.dumps(["0.55", "0.45"]),
        "clobTokenIds": json.dumps(["yes1", "no1"]),
        "volume": volume,
        "liquidity": "50",
    }


class GammaFeedTests(unittest.TestCase):
    def test_429_retries_then_succeeds(self):
        responses = [
            FakeResponse(429, headers={"Retry-After": "0"}),
            FakeResponse(200, payload=[row()]),
        ]
        with patch.dict(os.environ, {
            "GAMMA_MIN_REQUEST_INTERVAL_SECONDS": "0",
            "GAMMA_BACKOFF_BASE_SECONDS": "0.1",
            "GAMMA_REQUEST_RETRIES": "2",
        }), patch.object(market_data.S, "get", side_effect=responses), patch.object(
            market_data.time, "sleep"
        ):
            rows, status = market_data._request_page({"limit": 1}, retries=2)
        self.assertEqual(status, "ok")
        self.assertEqual(len(rows), 1)

    def test_keyset_page_shape_and_cursor(self):
        responses = [
            FakeResponse(
                200,
                payload={"markets": [row("200")], "next_cursor": "CURSOR-1"},
            ),
            FakeResponse(
                200,
                payload={"markets": [dict(row("100"), id="m2")], "next_cursor": None},
            ),
        ]
        with patch.dict(os.environ, {
            "GAMMA_MIN_REQUEST_INTERVAL_SECONDS": "0",
            "GAMMA_PAGE_SIZE": "1",
        }), patch.object(market_data.S, "get", side_effect=responses) as get:
            result = market_data.markets(2)
        self.assertEqual([m.id for m in result], ["m1", "m2"])
        self.assertEqual(get.call_args_list[1].kwargs["params"]["after_cursor"], "CURSOR-1")
        self.assertEqual(get.call_args_list[0].kwargs["params"]["closed"], "false")
        self.assertEqual(get.call_args_list[0].kwargs["params"]["active"], "true")

    def test_rate_limit_uses_last_good_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "markets.json")
            with patch.dict(os.environ, {
                "GAMMA_MARKET_CACHE_FILE": cache,
                "GAMMA_MIN_REQUEST_INTERVAL_SECONDS": "0",
                "GAMMA_BACKOFF_BASE_SECONDS": "0.1",
                "GAMMA_MAX_RETRY_WAIT_SECONDS": "1",
                "GAMMA_REQUEST_RETRIES": "0",
                "GAMMA_CACHE_MAX_AGE_SECONDS": "900",
            }):
                market_data._save_cache([row()])
                with patch.object(
                    market_data.S,
                    "get",
                    return_value=FakeResponse(429, headers={"Retry-After": "0"}),
                ), patch.object(market_data.time, "sleep"):
                    result = market_data.markets(1)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].id, "m1")
            self.assertTrue(market_data.feed_status()["stale"])

    def test_expired_cache_is_not_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = os.path.join(tmp, "markets.json")
            with patch.dict(os.environ, {
                "GAMMA_MARKET_CACHE_FILE": cache,
                "GAMMA_CACHE_MAX_AGE_SECONDS": "60",
            }):
                with open(cache, "w", encoding="utf-8") as f:
                    json.dump({
                        "cached_at": "2020-01-01T00:00:00+00:00",
                        "markets": [row()],
                    }, f)
                self.assertEqual(market_data._load_cache(), [])


if __name__ == "__main__":
    unittest.main()
