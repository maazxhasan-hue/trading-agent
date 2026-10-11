import json
import unittest

from strategy_proposals import StrategyProposal, aggregate_intent_id, proposal_from_vote


class StrategyProposalTests(unittest.TestCase):
    def proposal(self, **overrides):
        values = {
            "strategy_id": "momentum",
            "strategy_version": "momentum-v3",
            "data_version": "snapshot-v1",
            "validation_version": "paper-only",
            "market_id": "3045",
            "tradingsymbol": "SBIN-EQ",
            "exchange": "NSE",
            "timeframe": "5m",
            "lot_size": 1,
            "direction": 1,
            "entry_price": 100.0,
            "stop_price": 99.0,
            "target_price": 102.0,
            "confidence": 0.72,
            "rationale": "positive momentum with confirming volume",
            "features": {"r10": 0.012, "volume_ratio": 1.4},
            "signal_timestamp": 200.0,
            "data_timestamp": 199.0,
            "max_data_age_seconds": 10.0,
            "estimated_gross_edge": 1.2,
            "estimated_costs": {
                "fees": 0.1, "spread": 0.1, "slippage": 0.1, "taxes": 0.15,
            },
        }
        values.update(overrides)
        return StrategyProposal(**values)

    def test_proposal_serializes_costs_and_net_edge(self):
        proposal = self.proposal()
        row = proposal.to_dict()

        self.assertEqual(row["strategy_id"], "momentum")
        self.assertEqual(row["data_version"], "snapshot-v1")
        self.assertEqual(row["validation_version"], "paper-only")
        self.assertEqual(row["exchange"], "NSE")
        self.assertAlmostEqual(row["estimated_net_edge"], 0.75)
        self.assertEqual(json.loads(json.dumps(row))["features"]["r10"], 0.012)

    def test_proposal_checks_snapshot_freshness(self):
        proposal = self.proposal()

        self.assertTrue(proposal.is_fresh(now=205.0))
        self.assertFalse(proposal.is_fresh(now=211.0))
        self.assertFalse(
            self.proposal(data_timestamp=206.0, signal_timestamp=206.5).is_fresh(now=205.0)
        )

    def test_intent_id_is_stable_and_strategy_attributed(self):
        proposal = self.proposal()

        self.assertEqual(proposal.intent_id, self.proposal().intent_id)
        self.assertEqual(proposal.intent_id, self.proposal(signal_timestamp=200.5).intent_id)
        self.assertNotEqual(
            proposal.intent_id,
            self.proposal(strategy_id="mean_reversion").intent_id,
        )

    def test_neutral_vote_does_not_create_a_proposal(self):
        proposal_data = self.proposal().to_dict()
        proposal_data.pop("intent_id")
        proposal_data.pop("estimated_net_edge")
        self.assertIsNone(proposal_from_vote(0.0, **proposal_data))

    def test_directional_vote_sets_direction(self):
        proposal_data = self.proposal().to_dict()
        proposal_data.pop("intent_id")
        proposal_data.pop("estimated_net_edge")
        proposal_data.update(stop_price=101.0, target_price=98.0)

        proposal = proposal_from_vote(-0.5, **proposal_data)

        self.assertEqual(proposal.direction, -1)
        self.assertGreater(proposal.entry_price, proposal.target_price)

    def test_invalid_prices_confidence_and_costs_are_rejected(self):
        with self.assertRaises(ValueError):
            self.proposal(confidence=float("nan"))
        with self.assertRaises(ValueError):
            self.proposal(entry_price=0)
        with self.assertRaises(ValueError):
            self.proposal(direction=-1)
        with self.assertRaises(ValueError):
            self.proposal(estimated_costs={"fees": -0.01})

    def test_secret_shaped_feature_fields_are_rejected(self):
        with self.assertRaises(ValueError):
            self.proposal(features={"jwt_token": 1.0})

    def test_instrument_lot_size_is_explicit_and_positive(self):
        self.assertEqual(self.proposal(lot_size=10).lot_size, 10)
        with self.assertRaises(ValueError):
            self.proposal(lot_size=0)
        with self.assertRaises(ValueError):
            self.proposal(lot_size=1.5)

    def test_aggregate_order_intent_is_stable_for_same_proposals(self):
        proposals = [self.proposal(strategy_id="momentum"), self.proposal(strategy_id="event")]

        first = aggregate_intent_id("3045", "NSE", 1, 1, proposals)
        second = aggregate_intent_id("3045", "nse", 1, 1, reversed(proposals))

        self.assertEqual(first, second)
        self.assertNotEqual(first, aggregate_intent_id("3045", "NSE", 1, 2, proposals))


if __name__ == "__main__":
    unittest.main()
