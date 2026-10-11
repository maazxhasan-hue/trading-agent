# Implementation Plan: Live-Capable NSE/MCX Strategy Engine

**Goal:** Extend the repository's existing NSE/MCX multi-agent strategies with attributable broker-independent proposals, cost-aware chronological validation, and one guarded execution path. Preserve paper-only defaults; do not promise or force a return target.

**Architecture:** Existing strategy and agent modules produce proposals from a shared market snapshot. The current company orchestrator applies regime/debate and portfolio risk checks, and any accepted intent continues through the existing broker adapter, guarded live gate, and order manager. Validation evidence is generated separately from execution and cannot automatically arm live trading.

**Tech Stack:** Existing Python application, unittest test suite (pytest helpers imported by existing tests), existing Angel One adapter/order manager, existing paper tournament and walk-forward validation components. Tests use deterministic market fixtures and fake broker objects; no live broker login/order calls.

**Spec:** `docs/superpowers/specs/2026-10-11-live-capable-strategy-engine-design.md`

## Global Constraints

- Keep `LIVE_TRADING=false` and Angel One read-only/no-order mode as defaults. Never change VM services, deploy, test live login, or place any order during this work.
- Preserve the current explicit live arm, approval, kill switch, broker-evidence, margin, quote-freshness, and order reconciliation gates. Missing or stale evidence blocks.
- Strategy code must never own credentials, authenticate, instantiate a broker client, or place orders.
- No profit guarantee. ₹1,000/hour is an offline reporting benchmark only; ₹100 account infeasibility, insufficient evidence, costs, or risk limits must yield “no eligible trade.”
- Do not add new asset classes. Do not increase configured exposure, drawdown, or order limits. Do not introduce martingale/recovery sizing or automatic paper-to-live promotion.
- Check current Angel One/SEBI documentation during implementation when touching broker behavior. Do not infer undocumented API limits.
- Each task follows test-first: add a failing focused test, run it to confirm failure, implement the smallest change, rerun the focused test, then run adjacent regressions. No external credentials in fixtures or logs.
- Commit each coherent task on `codex/live-capable-strategy-design`; do not merge or deploy. Final verification uses the repository's actual CI commands and reports outcomes without claiming live recovery.

## Review Focus

1. Are proposal and validation interfaces small enough to fit the existing agent flow?
2. Does every strategy proposal pass through one existing fail-closed risk/order path?
3. Are costs, timestamps, sample sufficiency, chronological splits, and regime-specific results auditable?
4. Can any new code cause authentication, live mode, or order submission in paper tests or by default?
5. Does the ₹100 example correctly produce a no-trade outcome when actual lot size, fees, margin, or risk limits make execution infeasible?

## Implementation Tasks

### Task 1 — Map the actual strategy and execution call graph

**Files:** `signals.py`, `nse_agent.py`, `mcx_agent.py`, `nse_regime.py`, `nse_debate.py`, `angelone_adapter.py`, `angelone_order_manager.py`, `guarded_live_gate.py`; add/update a focused architecture note only if the existing docs do not identify entry points.

1. Before edits, trace and record the methods that create the market snapshot, gather agent votes/signals, classify regime, call the debate, size positions, invoke order manager, and report decision results for NSE and MCX.
2. Confirm whether MCX inherits the NSE company flow and identify its separate data/portfolio/evolution branches. Confirm which order manager is selected for Angel One.
3. Add a small regression test (or extend the closest existing test) asserting paper scan does not authenticate or submit an order when strategies evaluate. Use fakes; no network.
4. Run the focused test and existing import/runtime tests. Do not make behavior changes until this map is reflected in the implementation work.
5. Commit: `test: lock paper strategy evaluation away from broker writes`.

### Task 2 — Define and test the broker-independent strategy proposal

**Files:** create `strategy_proposals.py`; create `tests/test_strategy_proposals.py`; update `signals.py` only for a compatibility adapter if required by the call graph.

1. First add tests for a serializable proposal carrying stable strategy ID/version, market/instrument/exchange/timeframe, direction, entry/exit/stop assumptions, confidence, rationale/features, signal/data timestamps, maximum data age, and gross-edge/cost estimates. Add tests for no-signal, invalid/non-finite values, stale input, and deterministic intent identity.
2. Keep proposal generation a pure operation over an explicit shared snapshot and strategy output; it must not import the Angel One adapter, auth manager, environment secrets, or order manager.
3. Preserve existing `signals.build_signal` callers. Do not assume the standalone fair-value helper is part of the NSE/MCX company path; Task 3 should adapt the production `agent_votes` outputs to proposals.
4. Run proposal tests plus current signal/agent tests. Confirm proposals serialize without secrets or broker state.
5. Commit: `feat: add broker-independent strategy proposals`.

### Task 3 — Route existing strategy families through one snapshot and shared risk decision

**Files:** `nse_agent.py`, `mcx_agent.py`, `signals.py`, optionally `nse_regime.py`; create/extend `tests/test_strategy_orchestration.py`.

1. Add tests using a fixed snapshot and fake agents to prove the existing production vote families (momentum, mean reversion, event-driven, MCX commodity specialist, and cross-market arbitrage) see the same timestamped market data and emit attributable proposals. Treat regime and debate as shared context, not additional strategy votes.
2. Add tests that every proposal is visible in the decision record and rejected proposals carry a reason. Ensure stale quotes, absent regime/context, or risk disagreement cannot turn into an accepted intent.
3. Integrate proposals into the existing company orchestration and debate/risk path. Keep agent IDs and existing public interfaces compatible where feasible; do not add strategy-level broker calls.
4. Add a fake execution test verifying only a risk-approved, deterministic intent reaches the existing order manager and that duplicate intent evaluation does not submit twice. Keep live gates disabled and inject no real broker credentials.
5. Run focused orchestration/debate/risk tests and the full existing paper-runtime tests.
6. Commit: `feat: route NSE and MCX proposals through shared risk flow`.

### Task 4 — Validate net performance chronologically and by market regime

**Files:** `walk_forward.py`, `strategy_validation.py`, existing `mcx_paper_tournament.py` / `mcx_gen_evolution.py` only where integration is required; create/extend `tests/test_strategy_validation_costs.py`.

1. First add failing tests for gross-to-net return accounting using configured fees, spread/slippage, applicable taxes/charges, turnover, and rejected/unfilled trades. Validate insufficient samples, empty windows, regime splits, and no leakage from observations after a test window.
2. Extend the existing chronological evaluation/report output instead of creating a second promotion framework. Report sample count, net return/P&L, expectancy, drawdown, trade count, turnover, baseline comparison, per-window and regime metrics, and the ₹1,000/hour benchmark gap with explicit “research only” status.
3. A missing cost input, unavailable regime label, sample insufficiency, or unstable/out-of-sample loss must not report a strategy as eligible. Use explicit conservative config and preserve current defaults.
4. Add tests proving a favorable gross result can fail after costs and that hourly target attainment does not change trade eligibility or live gates.
5. Run walk-forward, calibration, MCX paper tournament/evolution, and validation tests.
6. Commit: `feat: report cost-aware walk-forward strategy evidence`.

### Task 5 — Keep promotion and broker execution fail-closed and auditable

**Files:** `guarded_live_gate.py`, `angelone_order_manager.py`, `angelone_adapter.py` only if required; create/extend `tests/test_strategy_live_safety.py` and the closest existing Angel One gate/order tests.

1. Add tests before changes showing that strategy validation alone cannot authorize an order, missing daily-loss configuration/readiness evidence cannot be inferred from the ₹1,000/hour benchmark, and paper mode remains unable to authenticate or submit.
2. Add only the minimum integration needed for a strategy's validation version/evidence to be carried into a proposed intent and decision audit record. The existing guarded gate remains the authority for any live order.
3. Enforce stable intent attribution/idempotency through the existing manager; do not add a second submission mechanism, weaken order reconciliation, or create implicit retries on unknown broker state.
4. Verify test configuration explicitly sets live mode false and Angel One read-only true; use fake broker methods that fail the test if login or order placement is attempted.
5. Run all guarded gate, broker evidence, reconciliation, adapter, strategy tests, and repository CI.
6. Commit: `test: enforce fail-closed strategy execution eligibility`.

### Task 6 — Operator documentation and final verification

**Files:** update the existing strategy/operations documentation selected from the repository's README/runbook; create/update a safe report example if none exists. Do not put secrets, actual account identifiers, or VM credentials in docs.

1. Document the existing NSE/MCX strategy flow, paper evaluation command, cost assumptions/configuration, decision and validation status meanings, and safe interpretation of the ₹1,000/hour benchmark.
2. Document live-readiness prerequisites as operator steps: broker confirmation of account/API policy and current SEBI requirements, verified static-IP configuration where required, user-selected daily loss limit, paper evidence, explicit approvals, and separate controlled test approval. Do not provide a command that turns live mode on unattended.
3. Run focused tests, full test suite, lint/type checks and CI as present in the repo. Inspect the final diff for changed live-mode defaults, secrets, unintended broker calls, new product classes, and order paths bypassing the gate.
4. Push changes to the feature branch and open/update a draft PR targeting the repository default branch. Include test/CI results and state clearly that VM deployment, live login, and live order testing were not performed.
5. Commit docs as `docs: explain strategy evaluation and live readiness`. Do not merge or deploy.
