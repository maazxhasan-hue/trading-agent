# Live-capable NSE/MCX strategy engine design

**Status:** Draft for operator review  
**Date:** 2026-10-11  
**Scope:** Strengthen the repository's existing NSE/MCX multi-agent system so strategies can use the Angel One execution path when separately authorized. This design does not enable live trading or promise returns.

## Intent and success criteria

The user wants the existing trading-agent system made stronger and live-capable, with ₹100 as the example starting capital and ₹1,000/hour as a desired outcome. The code should continue to support the repository's current NSE and MCX flows and Angel One adapter rather than introducing a separate trading product.

“Stronger” means strategies must demonstrate reproducible out-of-sample performance after fees, slippage, and instrument constraints, while respecting hard risk and operational gates. The ₹1,000/hour figure is a research benchmark to report, never a guaranteed return, a required trade trigger, or a reason to relax limits. With ₹100, the system may correctly conclude that a contract is unaffordable or that no trade is suitable.

Success means: each enabled strategy emits an attributable, testable proposal; the shared risk gate can reject it with a clear reason; the order manager is idempotent and uses broker-derived evidence; and all live paths remain disabled by default until an operator completes separate readiness and approval steps.

## Current repository shape

The repository already contains NSE/MCX agent entry points and an Angel One SmartAPI adapter/order manager. The production `NSETradingCompany.agent_votes` path emits momentum, mean-reversion, event-driven, MCX commodity-specialist, and cross-market-arbitrage votes, then applies regime classification, debate, and risk checks. The separate `signals.py` fair-value/momentum/reversion helpers are used by research validation code, not currently called by the company scan path; do not silently treat them as production strategies. The system also has MCX paper tournaments/evolution and chronological validation/agent-health checks. The Angel One adapter already has live/read-only separation, an order manager and a guarded live-order gate. This work should extend those paths rather than bypass or replace them.

The current production VM was observed with `TRADING_BACKEND=mcx`, `LIVE_TRADING=false`, auth status `AUTH_REQUIRED`, and a dirty `/opt/trading-agent` checkout. A read-only diagnostic was installed there, but the merged authentication change and this future strategy work have not been activated by restarting the trading service. Do not overwrite its unrelated local changes.

## Proposed architecture

### 1. Strategy proposal interface

Keep each strategy deterministic and independent from the broker. A strategy consumes normalized, timestamped market data and produces either no proposal or a proposal with:

- stable strategy ID/version, market/instrument, exchange and timeframe;
- direction and entry/exit/stop assumptions;
- confidence, feature snapshot, and concise rationale;
- signal time, data time, and maximum acceptable data age;
- estimated gross edge and estimated costs (fees, spread, slippage, and applicable taxes/charges);
- the data and validation version used to enable that strategy.

The initial candidate set is the production vote families already in `agent_votes`: momentum/trend, mean-reversion, event-driven, MCX commodity specialist, and cross-market arbitrage. Regime is shared context. The standalone fair-value helper is not wired into this path; integrate it only if separate tests establish a valid production role and compatible price semantics. Add breakout/range or other families only where a measurable gap exists and data supports validation. Do not interpret “all strategies” as every possible indicator combination. Do not expand instrument coverage to options, currencies, or other products in this scope.

### 2. Shared orchestration and Angel One execution

The NSE/MCX company orchestrator requests proposals from configured strategies using one shared market-data snapshot and one shared Angel One execution adapter. It records all proposals, applies the regime/debate checks, then sends surviving intents through the existing pre-trade gate and order manager. Strategies must not instantiate broker clients, authenticate, or place orders directly.

Order intents must have deterministic IDs/tags so a timeout or process restart cannot duplicate an accepted order. The order manager must reconcile order status before retrying an ambiguous submission. Cancel/modify/replace behavior remains under one order lifecycle owner. If broker state is unknown, block new exposure and report the state.

### 3. Validation and promotion

Use chronological walk-forward evaluation and paper tournaments already present in the repository. Compare each candidate against simple baselines and measure net P&L, expectancy, drawdown, turnover, calibration, trade count, and stability by market regime and instrument. Apply fees, slippage, lot sizes, margin, and rejected-order effects in simulation. Prevent look-ahead leakage and do not tune on the final holdout window.

A strategy is not live-eligible merely because it wins a backtest or meets an hourly target. Promotion requires configurable minimum sample sizes and stability gates, recorded evidence, fresh data, correct instrument metadata, and a passing operational readiness report. Thresholds must be explicit configuration with conservative defaults; adding a strategy must not weaken existing portfolio, drawdown, confidence, or live gates.

### 4. Risk and operational controls

Keep `LIVE_TRADING=false` and `ANGELONE_READONLY=true` (or an equivalent no-order setting) as defaults. Live capability remains behind the existing explicit arm, approved-runtime, guarded-autonomous, kill-switch, and broker-evidence gates. Do not add code that enables live mode, submits orders during tests, or automatically escalates a paper winner to live.

Before any order intent can reach Angel One, require: valid broker session; registered/verified source IP; market-open and fresh authorized quote; instrument/token/lot-size validation; available margin from broker evidence; net expected value after costs; price/liquidity bounds; per-position and aggregate exposure limits; daily drawdown/loss limit; correlation/concentration checks; protective exit verification; and idempotency/reconciliation. Any stale or missing evidence fails closed.

Use the existing configured risk limits as ceilings; do not increase them in this change. The owner must choose an acceptable maximum daily loss before any live activation. The ₹100/₹1,000-per-hour goal must never override affordability, loss limits, rate limits, or safety gates.

### 5. Authentication, rate limits, and broker compliance

Use the centralized Angel One authentication manager from the merged PR. Scans, dashboards, strategies, health checks, and agents must not trigger independent login. Keep single-flight, persistent cooldown, bounded retry and secret-redaction behavior.

Angel One's SmartAPI documentation currently describes a 1 request/second limit for password login and token generation, a cumulative order API limit, and registered static-IP validation for orders using static-IP-based keys. The implementation must use the official rate-limit configuration and must be rechecked against current SmartAPI docs and the account's API-key policy before rollout; do not hardcode undocumented block durations. See the official [SmartAPI rate-limit documentation](https://smartapi.angelone.in/docs/RateLimit), [SmartAPI order documentation](https://smartapi.angelone.in/docs/Orders), and [Angel One static-IP notice](https://smartapi.angelone.in/exchange-regulations). SEBI's retail algorithmic-trading circular and subsequent implementation updates must also be reviewed with the broker before an account is used live.

### 6. Reporting

For every scan, record a secret-free decision trail: data freshness, active strategy versions, each proposal/rejection reason, net-cost estimate, risk decision, broker connectivity state, and whether the system is paper-only or live-armed. Expose strategy metrics separately from account P&L. Never describe a model confidence score as a guaranteed win probability.

## Non-goals

- Guaranteeing ₹1,000/hour or any profit.
- Increasing leverage, relaxing risk controls, martingale/recovery sizing, or trading more frequently to force a target.
- Adding new exchanges/products outside the existing NSE/MCX scope.
- Enabling live orders, running a live login test, deploying/restarting the VM, or submitting test orders in this strategy implementation.
- Replacing the existing multi-agent architecture with a generic indicator collection.

## Implementation phases

1. Inspect and map the current signal, strategy-agent, validation, risk, order-manager, and readiness call paths.
2. Add proposal attribution and missing strategy families only where justified; keep proposal generation broker-independent.
3. Route proposals through shared data, debate/regime, risk and existing order-lifecycle gates; add unit and fake-broker tests.
4. Add net-of-cost chronological validation, regime reporting, promotion evidence, and paper-only evaluation for the ₹1,000/hour benchmark.
5. Run full tests/CI and keep the change on a feature branch/PR. No VM service restart or live API test is part of this implementation.

## Open decision before implementation

Choose the maximum permitted daily loss for a ₹100 account. Until specified, the implementation must retain current configured drawdown/exposure limits and fail closed when margin, lot size, fees, or account data make a trade infeasible. No live rollout may proceed without this value and separate operator approval.
