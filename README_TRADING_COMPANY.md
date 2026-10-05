# Trading Company Layer

## Pipeline

SCAN -> RESEARCH -> FAIR VALUE -> DEBATE -> RED TEAM -> RISK -> SIZING -> EXECUTION -> POST-TRADE -> AGENT HEALTH

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

Use conservative fractional Kelly and cap each position at 6% of bankroll. Additional volatility, correlation and liquidity limits can only reduce the size.

## Confidence

The execution gate requires >= 80% model confidence, but this is not a guarantee of winning. Calibration must be measured over time.

## Safety defaults

Paper mode is the default. Live execution is disabled until a real execution adapter is explicitly configured and authorized.

Credentials belong in protected secrets, never in Git.
