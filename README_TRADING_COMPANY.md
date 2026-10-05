# Trading Company Layer

> CI validation is required after each hardening step; live execution remains disabled by default.

## Pipeline

SCAN -> RESEARCH -> FAIR VALUE -> DEBATE -> RED TEAM -> PORTFOLIO RISK -> EXECUTION RISK -> SIZING -> EXECUTION -> RECONCILIATION -> POST-TRADE -> AGENT HEALTH

## Current safety gates

- Paper mode is the default.
- Live orders require explicit environment arming and protected credentials.
- Live orders are **cloud-only**: local/laptop runtimes are blocked by `runtime_guard.py`.
- Research must pass freshness/provenance gates before a trade can be proposed.
- Position size is capped at 6% of bankroll and fractional Kelly is used.
- Portfolio exposure and correlated exposure are capped.
- Daily loss and portfolio drawdown circuit breakers are enforced.
- Execution risk can reject thin order books or unsafe conditions.
- Live reconciliation uses venue-reported order status, cumulative matched quantity and average fill price; it never invents fills.
- Canceled/rejected/expired live orders are removed from active exposure.
- Losses are diagnosed before any strategy replacement is activated; no revenge trading or averaging down.

## Research sources

The system is designed to consume whatever approved connectors are configured for:
- market/order-book data
- crypto market data
- prediction-market data
- news
- X/social evidence
- macro/event calendars

A connector must be explicitly implemented and authorized; the agent should never pretend it accessed a source it could not access.

## Position sizing

Use conservative fractional Kelly and cap each position at 6% of bankroll. Additional volatility, correlation, liquidity, order-book depth and execution-risk limits can only reduce the size.

## Confidence

The execution gate requires >= 80% model confidence, but this is not a guarantee of winning. Calibration must be measured over time.

## Cloud runtime / laptop-off operation

The trading process is designed to run independently in the cloud. Once the cloud supervisor is running with persistent storage and restart-on-failure, the laptop can be powered off and the scan/research/execution/reconciliation loop continues.

The production image is `Dockerfile.production`. The Deplexo free-tier image remains a lightweight paper-validation deployment and is not the target for live capital.

## Live runtime locks

Live execution requires all of the following:

1. `LIVE_TRADING=true`
2. `LIVE_TRADING_ARM=I_UNDERSTAND_LIVE_TRADING`
3. `CLOUD_RUNTIME=true`
4. `LIVE_RUNTIME_APPROVED=true`
5. Protected Polymarket credentials available only as cloud runtime secrets.

The repository defaults all live switches to off. The live runtime must be explicitly approved only after production readiness checks.

## Validation before live trading

1. CI tests and compile checks pass.
2. Paper trading runs for a meaningful sample.
3. Calibration, drawdown, slippage and execution behavior are reviewed.
4. Production cloud persistence/restarts are verified.
5. Wallet/balance and order reconciliation are verified.
6. Live execution remains disabled until an explicit manual go/no-go decision.

No system in this repository guarantees profit. Paper performance is not proof of future results.

Credentials belong in protected secrets, never in Git.
