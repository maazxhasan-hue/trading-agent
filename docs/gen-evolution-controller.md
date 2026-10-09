# GEN evolution controller

This module adds a durable 3-hour tournament controller around the existing
MCX `TournamentLedger`.

- Starts a new session with its own population; previous runs cannot win the new session.
- Maintains a fixed active population and records parent-generation lineage as retired agents are replaced.
- Optionally initializes each replacement's isolated paper portfolio when a portfolio book is supplied.
- Persists the original start/deadline and session membership across restarts.
- At the deadline, evaluates only this session's generations using the ledger's existing one-hour target, minimum-trade, no-loss, drawdown and rule gates.
- Emits `NO_QUALIFIED_CHAMPION` when no candidate passes. It never fabricates a winner, starts Angel One validation, or enables live orders.

## Integration boundary

This controller is not yet wired into `nse_agent.py`, HQ telemetry, or a VM service. A runtime loop must call `tick()` and pass independently produced signals to the paper bridge. It must also supply the same persistent ledger and portfolio book used by the tournament.

The ₹1,000/hour target from ₹100 is not guaranteed. With a 6% notional cap, real MCX futures lots that cannot fit the cap must be skipped. Angel One validation remains deferred and live trading remains OFF.
