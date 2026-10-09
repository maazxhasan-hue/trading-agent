# Durable risk-state store

This PR adds SQLite persistence for a risk snapshot required by guarded live
order evidence. It is not connected to order submission and does not enable live
trading or start/deploy the Azure VM.

## Contract

An upstream source must supply equity, current exposure, daily P&L, peak/current
equity, order count, a passing independent risk-check flag, and a source label.
The caller must explicitly mark the source as independently verified. Missing,
non-finite, non-positive equity, negative exposure, fractional/negative order
counts, failed checks, stale/future snapshots, and snapshots from a different
India-local calendar day are rejected.

The store uses SQLite transactions and a single current snapshot. A new process
can read the persisted snapshot. This does not make an unverified source truthful:
the store is persistence and validation only. The upstream provider must reconcile
broker positions/orders and durable strategy intents before claiming verification.

## Safety limitations

- No automatic equity/P&L inference from account available funds.
- No default values when a source is absent.
- No broker margin calculation or exchange calendar in this change.
- No wiring into `AngelOneLiveEvidenceCollector` / order submission.
- Tests use synthetic values only; they do not establish live readiness.

Keep live trading disabled until source semantics, margin, market session,
protective exits, and fill reconciliation are implemented and independently
validated.
