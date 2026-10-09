import unittest
from unittest.mock import patch

from angelone_mcx_market_data import AngelOneMCXFeed


class FakeBroker:
    def __init__(self, rows):
        self.rows = rows

    def instruments(self, exchange):
        self.exchange = exchange
        return self.rows


class AngelOneMCXUniverseTests(unittest.TestCase):
    def make_feed(self, rows):
        feed = object.__new__(AngelOneMCXFeed)
        feed.broker = FakeBroker(rows)
        feed._instruments = {}
        feed._loaded_at = 0.0
        feed._history_cache = {}
        feed._last_history_request = 0.0
        return feed

    def test_all_futures_families_are_included_but_options_are_excluded(self):
        rows = [
            {"tradingsymbol": "GOLDM26OCTFUT", "instrument_token": "1", "instrument_type": "FUTCOM"},
            {"tradingsymbol": "COTTON26OCTFUT", "instrument_token": "2", "instrument_type": "FUTCOM"},
            {"tradingsymbol": "CARDAMOM26OCTFUT", "instrument_token": "3", "instrument_type": "FUTCOM"},
            {"tradingsymbol": "GOLD26OCTCE", "instrument_token": "4", "instrument_type": "OPTCOM"},
            {"tradingsymbol": "NO_TOKEN", "instrument_type": "FUTCOM"},
        ]
        feed = self.make_feed(rows)
        with patch.dict("os.environ", {"MCX_SYMBOL_FAMILIES": "ALL"}, clear=False):
            feed._load_instruments()
        self.assertEqual(
            set(feed._instruments),
            {"GOLDM26OCTFUT", "COTTON26OCTFUT", "CARDAMOM26OCTFUT"},
        )
        self.assertEqual(feed.broker.exchange, "MCX")

    def test_specific_family_filter_still_works(self):
        rows = [
            {"tradingsymbol": "GOLDM26OCTFUT", "instrument_token": "1", "instrument_type": "FUTCOM"},
            {"tradingsymbol": "COTTON26OCTFUT", "instrument_token": "2", "instrument_type": "FUTCOM"},
        ]
        feed = self.make_feed(rows)
        with patch.dict("os.environ", {"MCX_SYMBOL_FAMILIES": "GOLD"}, clear=False):
            feed._load_instruments()
        self.assertEqual(set(feed._instruments), {"GOLDM26OCTFUT"})


if __name__ == "__main__":
    unittest.main()
