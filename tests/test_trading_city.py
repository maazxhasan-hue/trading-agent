import json
import tempfile
import unittest
from pathlib import Path

from trading_city import TradingCity, build_market_universe, sync_tournament_from_evolution


class TradingCityTests(unittest.TestCase):
    def test_universe_accepts_only_fresh_mcxfutures(self):
        now = 1_800_000_000.0
        rows = [
            {"symbol": "GOLDM", "exchange": "MCX", "instrument_type": "FUT",
             "quote_timestamp": now - 2, "last_price": 72000, "lot_size": 1},
            {"symbol": "STALE", "exchange": "MCX", "instrument_type": "FUT",
             "quote_timestamp": now - 20, "last_price": 10, "lot_size": 1},
            {"symbol": "SPOT", "exchange": "MCX", "instrument_type": "SPOT",
             "quote_timestamp": now, "last_price": 10, "lot_size": 1},
            {"symbol": "BADLOT", "exchange": "MCX", "instrument_type": "FUT",
             "quote_timestamp": now, "last_price": 10, "lot_size": 0},
            {"symbol": "OTHER", "exchange": "NSE", "instrument_type": "FUT",
             "quote_timestamp": now, "last_price": 10, "lot_size": 1},
        ]
        result = build_market_universe(rows, now=now)
        self.assertEqual([x["symbol"] for x in result["eligible"]], ["GOLDM"])
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["rejected_count"], 4)
        self.assertIs(result["live_trading_enabled"], False)

    def test_missing_or_future_quote_fails_closed(self):
        now = 1000.0
        result = build_market_universe([
            {"symbol": "MISSING", "exchange": "MCX", "instrument_type": "FUT",
             "last_price": 10, "lot_size": 1},
            {"symbol": "FUTURE", "exchange": "MCX", "instrument_type": "FUT",
             "quote_timestamp": now + 1, "last_price": 10, "lot_size": 1},
        ], now=now)
        self.assertEqual(result["eligible"], [])
        self.assertTrue(all(x["reason"] == "STALE_OR_MISSING_QUOTE" for x in result["rejected"]))

    def test_duplicate_symbol_rejected(self):
        row = {"symbol": "GOLDM", "exchange": "MCX", "instrument_type": "FUT",
               "quote_timestamp": 100, "last_price": 10, "lot_size": 1}
        result = build_market_universe([row, row], now=100)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["rejected"][0]["reason"], "DUPLICATE_SYMBOL")

    def test_city_state_persists_and_live_is_forced_off(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "city.json"
            city = TradingCity(path)
            city.register_agent("research-1", "market_research", "ACTIVE")
            city.update_universe(build_market_universe([], now=100))
            city.update_tournament(stage="GEN_TOURNAMENT", status="RUNNING")
            snapshot = TradingCity(path).snapshot()
            self.assertEqual(snapshot["agents"]["research-1"]["role"], "market_research")
            self.assertEqual(snapshot["tournament"]["status"], "RUNNING")
            self.assertFalse(snapshot["risk"]["live_trading_enabled"])
            self.assertTrue(snapshot["risk"]["emergency_stop"])

    def test_corrupt_state_does_not_claim_readiness(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "city.json"
            path.write_text("{broken", encoding="utf-8")
            snapshot = TradingCity(path).snapshot()
            self.assertFalse(snapshot["state_recovered"])
            self.assertEqual(snapshot["runtime"]["health"], "INITIALIZING")
            self.assertFalse(snapshot["risk"]["live_trading_enabled"])

    def test_unknown_stage_rejected_and_live_candidate_needs_qualification(self):
        with tempfile.TemporaryDirectory() as temp:
            city = TradingCity(Path(temp) / "city.json")
            with self.assertRaises(ValueError):
                city.update_tournament(stage="LIVE", status="READY")
            with self.assertRaises(ValueError):
                city.update_tournament(stage="LIVE_CANDIDATE", status="RUNNING")
            city.update_tournament(stage="LIVE_CANDIDATE", status="QUALIFIED", champion_id="gen-1")
            self.assertEqual(city.snapshot()["tournament"]["champion_id"], "gen-1")
            self.assertFalse(city.snapshot()["risk"]["live_trading_enabled"])


    def test_evolution_sync_reports_champion_without_promoting_or_enabling_live(self):
        with tempfile.TemporaryDirectory() as temp:
            city = TradingCity(Path(temp) / "city.json")
            event = sync_tournament_from_evolution(city, {
                "status": "CHAMPION_RUNNING",
                "champion_generation": 7,
                "result": {"status": "SELECTED"},
                "deadline_at": "2030-01-01T00:00:00+00:00",
                "session_generations": [5, 6, 7],
            })
            snapshot = city.snapshot()
            self.assertEqual(event["champion_generation"], 7)
            self.assertEqual(event["next_stage"], "PAPER_VALIDATION_PENDING")
            self.assertEqual(snapshot["tournament"]["stage"], "GEN_TOURNAMENT")
            self.assertEqual(snapshot["tournament"]["champion_id"], "GEN-7")
            self.assertFalse(event["live_trading_enabled"])
            self.assertFalse(snapshot["risk"]["live_trading_enabled"])
            self.assertTrue(snapshot["risk"]["emergency_stop"])

    def test_evolution_sync_missing_status_fails_closed_to_running(self):
        with tempfile.TemporaryDirectory() as temp:
            city = TradingCity(Path(temp) / "city.json")
            event = sync_tournament_from_evolution(city, {})
            self.assertEqual(event["status"], "RUNNING")
            self.assertIsNone(event["champion_generation"])
            self.assertIsNone(event["next_stage"])
            self.assertFalse(event["live_trading_enabled"])


if __name__ == "__main__":
    unittest.main()
