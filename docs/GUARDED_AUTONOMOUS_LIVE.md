# Guarded autonomous live-order gate

The Angel One order manager now fails closed unless every order call provides
broker-derived safety evidence to `GuardedLiveOrderGate`. Existing call sites
that do not pass this evidence are intentionally blocked; this branch does not
turn on live trading.

## Required runtime gates

- `LIVE_TRADING=true`
- `LIVE_AUTONOMOUS_GUARDED_APPROVED=true`
- `CLOUD_RUNTIME=true`
- `LIVE_RUNTIME_APPROVED=true`
- `LIVE_TRADING_ARM=I_UNDERSTAND_LIVE_TRADING`
- Verified authorized quote, freshness, actual contract lot/quantity, broker
  margin, available funds, equity/exposure, daily P&L, drawdown, market session,
  risk checks, protective exit handling and broker reconciliation.

All settings default to blocked/off. These environment flags are not sufficient
on their own: the per-order evidence object is also mandatory.

## Emergency stop

Create the file configured by `LIVE_KILL_SWITCH_FILE` (default
`data/LIVE_KILL_SWITCH`) to block new orders. Alternatively set
`LIVE_KILL_SWITCH=true`. Remove the file only after an operator has diagnosed
the incident. The gate checks this file on every order attempt.

## Limits

Defaults: 6% of equity per position, 30% maximum total exposure, 3% daily loss
stop, 10% drawdown stop, quote age at most 10 seconds, and at most 10 orders per
day. Limits should be reviewed for instrument-specific margin and exchange
constraints. Futures notional sizing alone does not establish affordability:
broker margin must be verified for each order.

## Validation and limitations

Run `pytest -q tests/test_guarded_live_gate.py`. Tests use fake evidence and do
not qualify the system for live trading. Before any live trial, implement and
verify the production evidence provider and persistent cross-process duplicate
intent/order reconciliation, exercise protective exits and the kill switch in
paper/sandbox conditions, review logs, and obtain explicit operator approval.
No deployment or live-order enablement is part of this change.
