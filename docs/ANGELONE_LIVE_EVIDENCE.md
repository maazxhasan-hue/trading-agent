# Angel One live evidence collection boundary

This is a fail-closed integration seam for the guarded live-order gate. It is
not a live-trading enablement change and is not proof of live readiness.

## What the collector does

`AngelOneLiveEvidenceCollector` composes independently supplied providers for:
- an authorised, timestamped Angel One quote;
- instrument-master lot size and verified quantity semantics;
- a broker-backed margin estimate and available funds;
- durable risk state (equity, exposure, daily P&L, peak/current equity, order count);
- market session status;
- protective-exit verification; and
- broker/order reconciliation health.

If a provider is missing, raises, returns malformed values, or reports unverified
quote/margin/risk data, collection fails closed. No defaults are substituted for
missing account state. A false protective-exit or reconciliation result is
preserved as false so the downstream guarded gate blocks the order.

## Required before any live use

The repository still needs concrete, reviewed implementations of every provider.
In particular, do not treat `rmsLimit()` available cash as a contract margin
calculation, do not infer market-open status from a generic clock, and do not
mark protective exits healthy merely because an order was submitted. Verify
SmartAPI field semantics, MCX contract multipliers/lot sizes, margin responses,
order tags and partial-fill reconciliation against broker responses.

The collector is intentionally not connected to existing live order call sites
by this change. Those call sites remain fail-closed until the provider adapters
are implemented, exercised with recorded/sanitized broker fixtures, and reviewed.
Synthetic unit-test providers test the composition logic only; they are not broker
validation.

## Safe validation procedure

1. Keep `LIVE_TRADING=false` and do not set the live arm variables.
2. Implement and test each provider using read-only broker endpoints first.
3. Compare collected quotes, funds, positions and orders with the Angel One
   terminal and persist a reconciliation report.
4. Exercise stale/missing quote, missing margin, lot mismatch, session closed,
   protective exit missing, duplicate intent and kill-switch cases.
5. Keep live submission disabled until the full readiness review is explicitly
   approved. This change does not start Azure or deploy anything.
