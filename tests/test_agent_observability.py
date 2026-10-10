import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard import agent_observability as obs


class AgentObservabilityTests(unittest.TestCase):
    def test_roster_includes_required_strategy_and_debate_roles(self):
        agents = obs._parse_roster()
        ids = {item["id"] for item in agents}
        self.assertIn("orchestrator", ids)
        self.assertIn("market_scanner", ids)
        self.assertIn("momentum", ids)
        self.assertIn("bull", ids)
        self.assertNotIn("crypto_specialist", ids)
        self.assertGreaterEqual(len(agents), 20)

    def test_runtime_config_does_not_point_to_obsolete_gamma_feed(self):
        runtime = obs.ROOT / "config" / "runtime.yaml"
        config = runtime.read_text(encoding="utf-8")
        self.assertIn("provider: angelone_smartapi", config)
        self.assertIn("/data/angelone_instruments.json", config)
        self.assertNotIn("gamma_markets", config)

    def test_never_run_agents_are_not_falsely_marked_active(self):
        with tempfile.TemporaryDirectory() as temp:
            event_file = Path(temp) / "events.jsonl"
            with patch.object(obs, "EVENT_FILE", event_file):
                payload = obs.agent_snapshot()
            scanner = next(a for a in payload["agents"] if a["id"] == "market_scanner")
            self.assertEqual(scanner["status"], "NOT RUN / NO DATA")
            self.assertIsNone(scanner["last_seen"])
            self.assertEqual(scanner["research"], [])

    def test_profile_contains_only_actual_agent_analysis_events(self):
        with tempfile.TemporaryDirectory() as temp:
            event_file = Path(temp) / "events.jsonl"
            event_file.write_text(
                json.dumps({"type":"agent_analysis","ts":"2026-10-10T10:00:00+00:00",
                            "agent":"momentum","symbol":"TEST","thesis":"test thesis",
                            "evidence":["provider snapshot"]}) + "\n",
                encoding="utf-8")
            with patch.object(obs, "EVENT_FILE", event_file):
                profile = obs.agent_snapshot("momentum")
            self.assertIsNotNone(profile)
            self.assertEqual(profile["research"][0]["thesis"], "test thesis")
            self.assertEqual(profile["recent_evidence_count"], 1)
            self.assertEqual(profile["status"], "NOT RUN / NO DATA")

    def test_unknown_agent_is_not_returned(self):
        self.assertIsNone(obs.agent_snapshot("not-a-real-agent"))


if __name__ == "__main__":
    unittest.main()
