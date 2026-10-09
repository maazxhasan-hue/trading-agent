# Live evidence and numeric gate hardening

This change hardens validation only. It does not connect evidence providers to
order submission, enable live trading, or deploy/start the cloud VM.

## Changes

- The evidence collector requires the quote to identify the requested symbol
  token and exchange; it rejects non-positive prices and non-finite numeric data.
- The policy gate rejects NaN/infinity in all safety numbers and malformed
  fractional lot sizes, quantities, and order counts.
- Risk-limit environment values must be finite and positive; malformed settings
  fail at initialization rather than weakening a limit silently.
- Regression tests cover identity mismatch, invalid prices, non-finite evidence,
  fractional order counts, and invalid configured limits.

## Remaining live blockers

This is not a live-readiness signoff. A production MCX margin calculation,
verified exchange session/holiday provider, independently tested protective exits,
and full persistent strategy-intent/order/fill reconciliation are still missing.
The existing evidence-provider adapters are read-only and do not implement these
missing controls. Synthetic test evidence is not evidence of live broker readiness.
Keep `LIVE_TRADING=false`; do not deploy this branch as a live-order change.
