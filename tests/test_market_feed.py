import json
import os
import tempfile
import unittest
from unittest.mock import patch

import market_data


class FakeResponse:
    def __init__(self, status_code, payload=None, headers=None):
        self.status_code=status_code
        self._payload=payload
        self.headers=headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError("status=%s" % self.status_code)

    def json(self):
        return self._payload


def row():
    return {
        "id":"m1",
        "question":"Test market",
        "outcomePrices":json.dumps(["0.55","0.45"]),
        "clobTokenIds":json.dumps(["yes1","no1"]),
        "volume":"100",
        "liquidity":"50",
    }


class GammaFeedTests(unittest.TestCase):
    def test_429_retries_then_succeeds(self):
        responses=[
            FakeResponse(429,headers={"Retry-After":"0"}),
            FakeResponse(200,payload=[row()]),
        ]
        with patch.dict(os.environ,{
            "GAMMA_MIN_REQUEST_INTERVAL_SECONDS":"0",
            "GAMMA_BACKOFF_BASE_SECONDS":"0",
        }), patch.object(market_data.S,"get",side_effect=responses), patch.object(market_data.time,"sleep"):
            rows,status=market_data._request_page({"limit":1},retries=2)
        self.assertEqual(status,"ok")
        self.assertEqual(len(rows),1)

    def test_rate_limit_uses_last_good_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache=os.path.join(tmp,"markets.json")
            with patch.dict(os.environ,{
                "GAMMA_MARKET_CACHE_FILE":cache,
                "GAMMA_MIN_REQUEST_INTERVAL_SECONDS":"0",
                "GAMMA_BACKOFF_BASE_SECONDS":"0",
                "GAMMA_MAX_RETRY_WAIT_SECONDS":"1",
            }):
                market_data._save_cache([row()])
                with patch.object(market_data.S,"get",return_value=FakeResponse(429,headers={"Retry-After":"0"})), patch.object(market_data.time,"sleep"):
                    result=market_data.markets(1)
            self.assertEqual(len(result),1)
            self.assertEqual(result[0].id,"m1")


if __name__=="__main__":
    unittest.main()
