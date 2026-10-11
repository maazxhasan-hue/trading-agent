import unittest
import os
import time
from unittest.mock import Mock, patch
from types import SimpleNamespace

from nse_agent import NSETradingCompany, Signal
from strategy_proposals import proposals_from_votes


class StrategyOrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.market = SimpleNamespace(
            market_id="3045",
            tradingsymbol="SBIN-EQ",
            exchange="NSE",
            last_price=100.0,
            quote_timestamp=1000.0,
        )
        self.features = {"price": 100.0, "vol": 0.01, "r10": 0.02}
        self.votes = {
            "momentum-v3": 0.4,
            "mean_reversion-v3": -0.3,
            "event_driven-v3": 0.2,
            "mcx_commodity_specialist-v3": 0.5,
            "cross_market_arbitrage-v3": -0.1,
        }
        self.costs_bps = {"fees": 2, "spread": 1, "slippage": 3, "taxes": 1}

    def build(self, **overrides):
        values = {
            "votes": self.votes,
            "market": self.market,
            "features": self.features,
            "costs_bps": self.costs_bps,
            "data_version": "angelone-authorized",
            "validation_version": "paper-only",
            "timeframe": "5m",
            "signal_timestamp": 1001.0,
            "max_data_age_seconds": 10.0,
        }
        values.update(overrides)
        return proposals_from_votes(**values)

    def test_each_existing_vote_family_emits_attributed_proposal_from_same_snapshot(self):
        result = self.build()
        proposals = {proposal.strategy_id: proposal for proposal in result["proposals"]}

        self.assertEqual(
            set(proposals),
            {
                "momentum", "mean_reversion", "event_driven",
                "mcx_commodity_specialist", "cross_market_arbitrage",
            },
        )
        self.assertTrue(all(p.market_id == "3045" for p in proposals.values()))
        self.assertTrue(all(p.data_timestamp == 1000.0 for p in proposals.values()))
        self.assertTrue(all(p.data_version == "angelone-authorized" for p in proposals.values()))
        self.assertTrue(all(p.validation_version == "paper-only" for p in proposals.values()))
        self.assertEqual(proposals["mean_reversion"].direction, -1)
        self.assertAlmostEqual(proposals["momentum"].estimated_costs["fees"], 0.02)
        self.assertEqual(result["rejections"], [])

    def test_neutral_and_unregistered_votes_are_rejected_with_reason(self):
        result = self.build(votes={"momentum-v3": 0.0, "unknown-v1": 0.4})

        self.assertEqual(result["proposals"], [])
        self.assertEqual(
            {item["reason"] for item in result["rejections"]},
            {"WEAK_SIGNAL", "STRATEGY_NOT_REGISTERED"},
        )

    def test_missing_timestamp_or_cost_inputs_fail_closed(self):
        missing_timestamp = SimpleNamespace(**{**vars(self.market), "quote_timestamp": None})
        without_costs = self.build(market=missing_timestamp)
        without_tax_estimate = self.build(costs_bps={"fees": 2, "spread": 1, "slippage": 3})

        self.assertEqual(without_costs["proposals"], [])
        self.assertEqual(without_costs["rejections"][0]["reason"], "DATA_TIMESTAMP_MISSING")
        self.assertEqual(without_tax_estimate["proposals"], [])
        self.assertEqual(without_tax_estimate["rejections"][0]["reason"], "COST_INPUT_MISSING")

    def test_mcx_proposals_require_actual_contract_lot_size(self):
        mcx = SimpleNamespace(**{
            **vars(self.market),
            "exchange": "MCX",
            "tradingsymbol": "GOLDM26OCTFUT",
            "lot_size": 10,
        })
        result = self.build(market=mcx)
        missing = self.build(market=SimpleNamespace(**{
            **vars(mcx), "lot_size": None,
        }))

        self.assertTrue(all(proposal.lot_size == 10 for proposal in result["proposals"]))
        self.assertEqual(missing["proposals"], [])
        self.assertTrue(all(item["reason"] == "LOT_SIZE_MISSING" for item in missing["rejections"]))

    def test_company_uses_one_timestamped_snapshot_and_explicit_cost_config(self):
        company = object.__new__(NSETradingCompany)
        company.feed = SimpleNamespace(data_label="angelone-authorized")
        env = {
            "STRATEGY_COST_FEES_BPS": "2",
            "STRATEGY_COST_SPREAD_BPS": "1",
            "STRATEGY_COST_SLIPPAGE_BPS": "3",
            "STRATEGY_COST_TAXES_BPS": "1",
            "MARKET_INTERVAL": "5m",
        }

        with patch.dict(os.environ, env):
            result = company.strategy_proposals(
                self.market, self.features, self.votes, signal_timestamp=1001.0
            )

        self.assertEqual(len(result["proposals"]), 5)
        self.assertTrue(all(p.data_timestamp == 1000.0 for p in result["proposals"]))
        self.assertTrue(all(p.signal_timestamp == 1001.0 for p in result["proposals"]))
        self.assertTrue(all(p.data_version == "angelone-authorized:5m:v1" for p in result["proposals"]))

    def test_live_path_blocks_before_broker_calls_without_approved_proposals(self):
        company = object.__new__(NSETradingCompany)
        company.execution = SimpleNamespace(enabled=True, funds_available=Mock(return_value=1000))
        company.journal = SimpleNamespace(record=Mock())
        company.open_positions = {}
        company.traded_today = set()
        company.backend = "angelone_nse"
        market = SimpleNamespace(
            market_id="3045", tradingsymbol="SBIN-EQ", exchange="NSE", last_price=100.0,
        )
        signal = Signal(market, 1, 0.8, 0.9, 0.01, "test")

        company.paper_or_live(signal)

        company.execution.funds_available.assert_not_called()
        company.journal.record.assert_called_once()

    def test_paper_only_validation_cannot_reach_live_broker_calls(self):
        company = object.__new__(NSETradingCompany)
        company.execution = SimpleNamespace(enabled=True, funds_available=Mock(return_value=1000))
        company.journal = SimpleNamespace(record=Mock())
        company.open_positions = {}
        company.traded_today = set()
        company.backend = "angelone_nse"
        market = SimpleNamespace(
            market_id="3045", tradingsymbol="SBIN-EQ", exchange="NSE",
            last_price=100.0, quote_timestamp=time.time(), lot_size=1,
        )
        now = time.time()
        result = self.build(market=market, signal_timestamp=now)
        proposals = tuple(result["proposals"])
        self.assertTrue(proposals)
        self.assertTrue(all(p.validation_version == "paper-only" for p in proposals))
        signal = Signal(market, 1, 0.8, 0.9, 0.01, "test", strategy_proposals=proposals)

        company.paper_or_live(signal)

        company.execution.funds_available.assert_not_called()
        self.assertEqual(company.journal.record.call_args.args[0], "LIVE_SIGNAL_BLOCKED_BY_STRATEGY")

    def test_approved_debate_signal_and_journal_retain_proposals_and_rejections(self):
        company = object.__new__(NSETradingCompany)
        votes = {name: 0.5 for name in self.votes}
        qualified = list(votes)
        debate = SimpleNamespace(
            decision="BUY", direction=1, agreement=0.9, conflict=0.1,
            score=0.8, confidence=0.8, rationale="test consensus",
            challenges=[], votes=votes,
        )
        company.learning = SimpleNamespace(
            qualified_agents=Mock(return_value=(qualified, {}))
        )
        company.debate = SimpleNamespace(run=Mock(return_value=debate))
        company.journal = SimpleNamespace(record=Mock())
        features = {
            "r5": 0.01, "r20": 0.02, "vol": 0.01, "breakout": 0.01,
            "volume_ratio": 1.5, "reversion": 0.0,
        }
        proposals = self.build(votes=votes)["proposals"]
        rejections = [{"strategy_id": "mean_reversion", "reason": "NO_SIGNAL"}]

        with patch("nse_agent.hq_events.activity"), patch("nse_agent.hq_events.snapshot"):
            signal = company.signal(
                self.market, features, votes, proposals, rejections
            )

        self.assertIsNotNone(signal)
        self.assertEqual(signal.strategy_proposals, tuple(proposals))
        self.assertEqual(signal.proposal_rejections, tuple(rejections))
        record = company.journal.record.call_args.kwargs
        self.assertEqual(record["strategy_proposals"], [p.to_dict() for p in proposals])
        self.assertEqual(record["proposal_rejections"], rejections)


if __name__ == "__main__":
    unittest.main()
