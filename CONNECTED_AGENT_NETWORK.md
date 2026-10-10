# Connected Agent Network — Strengthening Plan

## Purpose

Make every logical agent a specialist in a coordinated research network instead of a disconnected chatbot. This document defines the target contract; it does **not** claim that every role or connector is already running. The runtime must report actual heartbeats, source access, and test results.

## Shared cycle and evidence bus

Each scan receives a unique `cycle_id`. Agents publish versioned, structured messages to a durable event bus and append-only decision journal. Messages include the agent identity, creation and expiry times, source URL/provider, source timestamp, instrument, claim, confidence, uncertainty, supporting and contradicting evidence, and dependencies.

Agents read one another's outputs by cycle ID. New evidence creates a new version rather than silently overwriting a prior claim. Deduplicate the same underlying source across agents so ten copies of one rumor never count as ten independent confirmations. Store provenance and preserve dissent.

If the event bus, journal, required role, freshness check, or broker reconciliation is unavailable, the system degrades safely and produces **NO TRADE**.

## Stronger specialist network

- **Market Scanner:** rank the available universe by freshness, tradability, and potential edge; never imply coverage of 500–1,000 markets unless the provider actually returned and processed them.
- **Data Quality:** detect stale timestamps, missing fields, outliers, conflicting providers, duplicate stories, and suspiciously unchanged prices.
- **Regime Detector:** classify trend/range/volatility regime and specify conditions that would invalidate the classification.
- **Fair Value + Quant:** independently estimate value and uncertainty; include fees, spread, slippage, settlement/expiry rules, and calibration history.
- **Liquidity / Microstructure:** inspect depth, spread, impact, and whether the proposed size can be filled safely.
- **Macro / Event Research:** track scheduled announcements, market hours, expiry/settlement events, and event-driven gap risk.
- **Strategy specialists:** momentum, mean reversion, event-driven, volatility regime, breakout, order-book imbalance, cross-market relationships, and crypto/prediction-market specialists only where a supported venue and lawful data connector exist.
- **X / Social Research:** use authorized access; record original URL/post ID and timestamp; distinguish original reporting from reposts/rumors; cross-check material claims against independent reliable sources. Social sentiment alone is never a trade trigger.
- **Bull / Bear / Skeptic:** each independently constructs a thesis; each must read and answer the strongest opposing evidence rather than merely vote.
- **Red Team:** search for look-ahead bias, data leakage, crowded/correlated exposure, manipulation, liquidity traps, regime changes, and failure scenarios.
- **Independent Validator:** measure calibration, walk-forward/out-of-sample results, sample size, and regression against the incumbent before a candidate can qualify.
- **Risk / Portfolio:** independently apply capital, affordability, exposure, correlation, daily loss, drawdown, and venue-specific constraints. Other agents cannot override these controls.
- **Execution + Execution Quality:** only the approved execution adapter may submit orders. Track acknowledgements, partial fills, cancel/replace state, actual costs, and venue-reported reconciliation.
- **Post-Trade + Agent Health:** attribute outcomes to data, thesis, sizing, regime, and execution; create tests; quarantine broken agents; keep replacements in shadow/paper mode until validated.
- **Audit + Treasury:** maintain append-only decision lineage and separately capped service spending; never silently fund subscriptions from trading capital.

## Debate and decision protocol

1. Scanner creates a universe snapshot; data-quality and freshness checks run before analysis.
2. Regime, event, social, liquidity, fair-value, and strategy agents publish evidence independently.
3. Quant normalizes comparable proposals and estimates expected value after costs.
4. Bull and Bear write separate theses. Skeptic challenges both; Red Team records explicit objections and counterexamples.
5. Required agents issue explicit APPROVE, REJECT, or ABSTAIN with evidence references. Any reject, abstention, missing role, stale evidence, unresolved material objection, or failed risk gate means **NO TRADE**.
6. Risk runs as a deterministic independent gate. CEO/orchestrator summarizes the outcome but cannot override it.
7. Execution is attempted only in the configured mode and only once for a unique idempotency key. Unknown order status blocks new exposure until reconciliation.
8. Post-trade outcomes return to the same evidence bus and validation journal.

Unanimity is a governance gate, not a guarantee that a decision is correct. Agent count and confidence scores must never be used as a substitute for independent evidence.

## Learning and stronger replacements

Use versioned strategy/agent candidates, shadow runs, paper tournaments, walk-forward validation, calibration checks, and regression tests. A candidate replaces an incumbent only after meeting predeclared metrics on unseen data and passing the same risk/security tests. Do not train and score on the same observations. Preserve rollback and a complete audit trail. A loss does not trigger revenge trading or automatic escalation in size.

## Runtime truth and observability

The HQ should show live/last-seen status, current cycle ID, source freshness, evidence count by independent source, disagreement, veto reason, latency, model version, and order/reconciliation state. Clearly distinguish configured, connected, healthy, and actively producing results. Do not animate or display fake agents, fabricated data, or inferred broker fills.

## Non-negotiable safety defaults

- Paper mode by default; live execution remains disabled until a separate explicit operator approval.
- Research browsers and source connectors are read-only and receive no broker credentials or order permissions.
- Respect provider terms, rate limits, authentication, and access controls; do not bypass site protections.
- Position sizing is bounded by the existing policy; additional checks can only reduce permitted size.
- No trade is required. If the evidence or affordability is inadequate, report NO TRADE.
- No profit, win rate, or model confidence is guaranteed.
