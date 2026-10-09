# GEN evolution controller

This module adds a durable 3-hour tournament controller around the existing
MCX `TournamentLedger`.

## Current behavior

- Maintains a configured number of active GEN tournament records.
- Replenishes retired generations while the tournament is running and records
  parent-generation lineage.
- Persists the original start/deadline across process restarts.
- At the deadline, asks `TournamentLedger.select_champion()` to apply the
  existing one-hour target, minimum-trade, no-loss, drawdown and rule checks.
- Emits `NO_QUALIFIED_CHAMPION` when no candidate passes. It never fabricates a
  winner, starts Angel One validation, or enables live orders.

## Important integration boundary

This is a controller module, not yet wired into the main runtime/HQ in this
change. The service loop must call `tick()` on a schedule and pass independently
produced signals to the existing paper bridge. Do not treat a selected champion
as evidence that ₹1,000/hour is achievable from ₹100. With the 6% notional cap,
the existing paper book correctly skips futures contracts whose real lot cannot
fit within the cap.

Live trading remains disabled; Angel One validation remains deferred.
