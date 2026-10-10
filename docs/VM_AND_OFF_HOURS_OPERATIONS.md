# Azure VM Reliability and Off-Hours Intelligence

## Intended behavior

The VM is the always-on runtime; the user's laptop is only a client. This is a target design until the acceptance tests below have passed on the actual VM. No code or CI change in this document deploys a service, starts the VM, or enables live orders.

## Market-session state machine

Use the configured Angel One exchange/segment and Asia/Kolkata timezone. Resolve regular sessions from the exchange calendar/provider when available, including holidays, special sessions, and changed timings. A weekday/time heuristic is a fallback for display only, never enough by itself to authorize a live order.

- `PRE_OPEN`: refresh instrument master/calendar, check broker session, reconcile any carried broker state, and prepare the candidate universe.
- `OPEN`: request authorized fresh quotes and perform normal scan/debate/risk checks. Entries are allowed only when the backend confirms the venue/session is open and all other gates pass.
- `CLOSED`: disable new live entries. Continue research-only tasks, data-quality checks, next-session planning, learning reviews, and paper validation.
- `UNKNOWN` or calendar/provider disagreement: fail closed for live entries, record the reason, and alert.
- `REOPENING`: discard expired intraday quotes/signals; refresh the instrument master and current quotes, reconcile orders/fills/positions/funds, then run the full evidence and unanimous-debate flow again.

Venue-specific trading hours and holidays must come from authoritative exchange/broker sources; do not hard-code MCX close time as universal because commodity contracts and sessions may vary.

## Off-hours research queue

During closed sessions, the service should continuously process bounded, resumable jobs:

1. Fetch authorized market announcements, company filings/corporate actions, macroeconomic calendars, exchange circulars, and permitted news sources.
2. Collect global-market/commodity context relevant to the next eligible Indian session.
3. Refresh the instrument master and calendar where provider/API rules allow. Cache historical candles and the last-known quotes with source and timestamp; label quotes as historical/stale and never use them as live execution prices.
4. Review closed-trade autopsies, actual fees/slippage, GEN scorecards, drawdown, calibration, and failed hypotheses.
5. Generate a versioned next-session watchlist with thesis, source links/timestamps, counter-thesis, catalyst/event risk, invalidation conditions, expected spread/slippage, and missing evidence.
6. Test candidate strategy changes only in isolated paper/out-of-sample runs. Promotion to the next validation stage requires measured results and explicit gates; off-hours research cannot arm live trading or change the position-risk limit.
7. Persist job cursor, source IDs, timestamps, outputs, errors, and completion state so VM restarts resume rather than silently restart from zero.
8. If a source is unavailable, rate-limited, or stale, record the failure and continue independent tasks within rate limits. Never invent missing data or treat rumors as confirmed facts.

## VM operational requirements

- Run the engine under a dedicated non-root OS user via systemd (or an equivalently supervised service); keep the HQ web process separate and bound to localhost behind an authenticated access layer.
- Enable service startup at boot and bounded restart/backoff. Do not run a second copy of the engine after manual restart; enforce a single-instance lock/lease.
- Persist decision journal, paper portfolio, trade ledger, GEN state, research queue, and browser profiles on durable disk. Back up state and test restoration; do not put secrets in logs or backups without encryption.
- Store Angel One credentials only in a VM-local secret file or secret manager with least-privilege file access. Never commit credentials, echo them, or send them in chat.
- On boot/reconnect: restore durable state, connect to SmartAPI, refresh instruments/session status, reconcile broker orders/fills/positions/funds, verify protection and kill switch, and only then consider a new entry. If reconciliation is incomplete, no new entry.
- Expose a local health endpoint/heartbeat that checks process liveness, last successful data timestamp, broker connection state, last reconciliation, journal writability, disk space, and active-cycle lease. A process merely existing is not enough to report healthy.
- Alert on repeated restart, auth/TOTP failure, feed staleness, rate limits, unreconciled orders, state-write errors, disk exhaustion, and kill-switch activation.
- Use VM clock synchronization and Asia/Kolkata timestamps for session logic; store event timestamps with timezone/UTC provenance.

## Required acceptance tests before calling it VM-ready

1. Reboot the VM and verify the engine/HQ start once, recover state, and report health.
2. Kill the process during research and verify the job resumes without duplicate entries.
3. Disconnect/reconnect network and expire SmartAPI auth; verify new entries remain blocked until refreshed and reconciled.
4. Run on a market holiday, weekend, and after the configured session closes; verify no live entries and continued research queue progress.
5. Reopen after a closure; verify old quotes/signals are discarded and a new scan/debate is performed.
6. Simulate unknown/partial/rejected broker order state and failed persistence; verify fail-closed behavior.
7. Confirm durable journal/GEN state survives restart and the single-instance lock blocks duplicate engines.
8. Verify all service secrets are absent from Git, logs, dashboard, and research browser profiles.
9. Run paper-only on the actual Azure VM against authorized Angel One read-only data, verify source timestamps/actual lot and margin details, and record evidence.
10. Keep `LIVE_TRADING=false` and read-only/paper mode until a separate operator-reviewed approval. CI green or successful off-hours research is not live-trading approval.

## Current implementation boundary

This document and configuration describe required behavior and acceptance criteria. They do not prove the current engine already runs off-hours research, uses the session state machine, or is deployed to Azure. Those capabilities must be wired into the runtime and validated with the tests above before marking this complete.
