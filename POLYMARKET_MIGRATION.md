# Polymarket migration

This branch makes Polymarket the primary venue for the autonomous trading agent. Indian broker/MCX adapters remain available for rollback but are no longer the default backend.

## Runtime
- Public market discovery: Polymarket Gamma API
- Price/order execution: Polymarket CLOB
- Chain: Polygon (137)
- Default mode: paper/simulation
- Live mode remains explicitly locked behind LIVE_TRADING + LIVE_TRADING_ARM + CLOUD_RUNTIME + LIVE_RUNTIME_APPROVED
- Laptop is not required once the agent is deployed on the cloud VM.

## Required live secrets (never commit)
PK=
CLOB_API_KEY=
CLOB_SECRET=
CLOB_PASS_PHRASE=

## Safety
The agent must not trade when the market feed is stale, the collateral balance cannot be reconciled, risk limits fail, or the live runtime is not explicitly approved. Start with paper mode and validate order reconciliation before enabling live orders.
