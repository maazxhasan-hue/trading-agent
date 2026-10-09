# Angel One read-only provider adapters

This change adds concrete, read-only adapters for verified Angel One SmartAPI
observations. It does not enable live trading, wire these providers into order
submission, start the Azure VM, or place/modify/cancel orders.

## Implemented

- Quote provider requests the exact requested token and exchange, checks token
  identity, requires a positive finite LTP and parses a broker exchange timestamp.
- Instrument provider requires one exact exchange + symbol + token match and
  verifies the requested quantity is a positive multiple of the broker instrument
  master's lot size.
- Account snapshot collects broker-reported available funds, day/net positions
  and order book from read-only methods.
- Conservative structural reconciliation rejects malformed orders/positions and
  impossible filled quantities.

## Still intentionally unavailable

These adapters do not calculate MCX contract margin. `funds_available` is only
an account funds field and must never be treated as required margin. Nor do these
adapters establish market-open/holiday status, durable equity/P&L/exposure state,
protective-exit health, or strategy-intent-to-fill reconciliation. Those providers
must remain absent or false until separately implemented and verified; the
existing collector/gate must therefore continue to block live order approval.

The timestamp parser accepts the exchange timestamp formats already handled by
the MCX market-data feed. If Angel One returns an unsupported or missing format,
the quote is rejected rather than assigning the local fetch time.

## Validation

Unit tests use deterministic fake broker responses to exercise adapter behavior;
they do not contact Angel One and are not evidence of live broker readiness.
Keep `LIVE_TRADING=false`, do not set live arm variables, and leave Azure stopped
until an explicit readiness review.
