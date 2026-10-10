# Master Trading Agent Specification

Status: consolidated product specification. This document records the intended behavior; it is **not evidence that every feature is implemented or live-ready**. Track implementation through code, tests, paper validation, and an explicit operator approval.

## 1. Goal and venue

- Build an autonomous Indian-market trading agent using Angel One SmartAPI.
- Current target universe: Angel One instruments eligible for the selected Indian-market segments; prioritize supported cash-market instruments when affordable. MCX futures remain in scope only when actual contract lot size, margin, charges, and risk budget are affordable.
- Do not use Binance or crypto trading in the current live-trading plan.
- Discover the actual available instrument master at runtime. A scan ceiling of 1,000 markets is a ceiling, not a claim that 1,000 tradable contracts exist.
- Scan on a five-minute cycle when market/session/API conditions allow. Respect exchange trading hours, holidays, rate limits, and stale-data checks.

## 2. Capital, compounding, and trade sizing

- Starting live capital: ₹100, supplied by the operator.
- Milestone target: grow capital to ₹1,000 through compounding. This is an objective, not a promise or guaranteed return.
- One active trade/position at a time. Do not open a new entry until the previous trade's broker order/fill/position state has been reconciled.
- Maximum position notional: 6% of the latest reconciled available trading capital. This is a **position-value cap**, not 6% stop-loss risk.
- After every fully reconciled closed trade, calculate actual net P&L after brokerage, taxes/levies, slippage, and other charges; update the capital ledger; recalculate the next 6% cap from the updated capital.
- Never reset capital or grant a replacement GEN a fresh bankroll. All generations share the same operator-approved account and remaining capital.
- Round quantity down to valid exchange lot/quantity increments. Check minimum order size, margin, available funds, charges, liquidity, spread, and broker/exchange restrictions before any order.
- If no valid instrument fits the 6% position cap and account requirements, skip the trade. Never bypass the cap, borrow extra funds, or force a trade to meet a target.
- No guarantee of profit. ₹100 may be too small for many instruments once minimum quantity, margin, and charges are considered.

## 3. One-trade-at-a-time execution cycle

1. Fetch and validate current Angel One instrument master, quotes, market session, account funds, and existing orders/positions.
2. Scan eligible instruments and score candidate setups using strategy signals, liquidity/spread, fees, slippage, and risk.
3. Select at most one eligible trade, only if all gates pass.
4. Before sending any order, re-check capital, quantity, session, quote freshness, and risk limits.
5. Submit only through the approved Angel One adapter. Track order acknowledgement, fills, rejects, partial fills, exits, and protective orders.
6. Do not assume an order succeeded from an API request alone. Reconcile broker orders, fills, and positions.
7. On close, calculate realized net P&L and update the durable capital/trade ledger.
8. Only then may the next scan/entry cycle begin.

## 4. GEN tournament, elimination, and replacement

- Multiple candidate GENs/strategies compete in isolated paper environments; prevent look-ahead bias, shared-position contamination, and untracked risk.
- Record scorecards for net P&L after fees/slippage, trade count, win/loss distribution, drawdown, execution assumptions, and rule violations.
- A paper GEN that incurs a losing closed trade is retired under the user's strict one-loss elimination rule. Preserve its logs, parameters, market context, and loss autopsy; do not delete its knowledge.
- A replacement GEN inherits research and lessons, not a fresh capital balance. It must be evaluated against the same risk rules and benchmarked out-of-sample/paper before it can be considered stronger.
- The aspirational tournament objective is a champion reaching ₹1,000 net simulated P&L within a 60-minute window, subject to minimum sample/risk criteria. This is a tournament target only—not a forecast, live objective that overrides safety, or guaranteed result.
- Promotion flow: GEN tournament champion → Angel One **read-only/paper validation** using real authorized quotes and actual instrument/lot/margin data → evidence-based live candidate → separate explicit operator approval.
- In live mode, if a GEN incurs a losing closed trade, retire that GEN and immediately block new entries. First reconcile broker state and safely manage any open position/orders; do not abandon an open position or cancel protection blindly. Spawn/research a replacement, but keep it in paper/validation until the promotion gates and required operator approval pass.
- A losing trade does not prove a strategy is universally bad; nevertheless, the configured one-loss policy retires that generation. Do not revenge trade or automatically increase size.
- If no qualified replacement exists, keep new entries stopped.

## 5. Safety, risk, and fail-closed behavior

- Live trading is disabled by default. No environment flag, tournament win, GEN replacement, or CI result alone may enable it.
- Require a separate, explicit operator approval before live order entry is enabled.
- Fail closed on stale/missing quotes, closed or unverified market session, unknown order/fill state, unhealthy broker reconciliation, missing/failed protective-exit handling, insufficient funds/margin, invalid quantity, or breached risk limits.
- On API/network errors or uncertain order status: block new entries, query/reconcile broker state, preserve protection for existing positions, and alert the operator.
- On emergency stop, risk-limit breach, or broken protective-exit/reconciliation controls: halt new entries and follow a tested position-management/reconciliation procedure.
- A software process shutdown must not be treated as proof that broker-side orders or positions are closed. Verify actual broker state.
- Use durable audit logs for every decision, signal, order request, acknowledgement, fill, exit, risk rejection, GEN retirement, replacement, and promotion.
- Secrets/API credentials must be stored securely and never committed to the repository or logs.

## 6. Research and adaptation

- Maintain a research/learning archive with post-trade autopsies, failed hypotheses, market context, fees/slippage observations, and versioned strategy parameters.
- Candidate agents may research market news and public information when permitted, and debate/compare hypotheses, but no unverified claim may bypass the risk gate.
- Strategy mutation, cloning, or agent creation must happen in isolated test environments; newly created agents do not inherit live permission.
- Do not use online sentiment or a single backtest result as sufficient proof of profitability. Include out-of-sample and paper validation.

## 7. Runtime and operations

- Intended operation: run on an Azure VM so trading can continue while the user's laptop is off, subject to VM uptime, network, broker session, exchange hours, and API availability.
- Laptop shutdown should not stop a healthy cloud VM. If the VM/process or connection fails, trading cannot continue until service is restored; on restart, reconcile broker state before considering new entries.
- Provide health checks, durable state recovery, structured logs, alerts, controlled restarts, and a kill switch.
- Do not deploy or start a live runtime as part of documentation/CI work. Deployment and live activation require explicit approval.
- Self-funding subscriptions, automatically cloning replacement agents, and shutting down optional services when funds reach zero are future operational ideas, not permission to spend account funds or increase trading risk. They must be separately specified, budget-capped, and operator-approved before implementation.

## 8. Required validation gates

- Unit tests: capital calculation, 6% notional cap, quantity rounding, one-open-position invariant, net P&L/charges, GEN retirement, loss-autopsy persistence, replacement gating, restart recovery, and fail-closed behavior.
- Integration tests: Angel One adapter errors, partial fills, rejected orders, stale quotes, rate limits, market closure, unknown order state, protective exits, and reconciliation.
- Paper validation: actual authorized Angel One instrument master/quotes, actual lot/quantity increments, margin/funds evidence, charges/slippage, session status, and order/position reconciliation. No live orders during this phase.
- Operational tests: restart after crash, VM/network outage, duplicate order prevention, state persistence, and emergency-stop behavior.
- CI green means automated repository checks passed only. It does not prove live-account validation or profitability.
- Only after all evidence is reviewed may a candidate be marked live-ready; live trading remains disabled until the operator separately authorizes it.

## 9. Trading City HQ visual and functional specification

Use the uploaded 15-second video as the visual reference for the desired HQ—not as proof of an existing implementation.

### Visual direction
- Full-screen, dark/black futuristic command-center interface.
- Large central animated neural/network visualization: distinct clusters/nodes for agents, strategies, risk, execution, research, and learning.
- Animated lines/pulses show real messages/events between services; disconnected or unhealthy services must visibly show as disconnected, not keep animating as if healthy.
- Subtle cyan, magenta, white and restrained red/amber accents on a dark background. Avoid cluttering the main network with tiny unreadable labels.
- Compact monitoring panels along the bottom and/or sides, inspired by the video: agent logs, scan status, market feed, strategy metrics, P&L, risk gauges, recent events and service health.
- Responsive layout for laptop first; mobile can show a simplified, legible view.

### Functional panels
- **Command Center:** current mode (PAPER/LIVE), live trading enabled/disabled, capital, ₹1,000 target progress, latest reconciled P&L, current 6% position cap, open position count, scan heartbeat and kill-switch state.
- **Agent Network:** each GEN/service has an ID, status, last heartbeat, role and actual event connections. Show spawning, retirement, validation and promotion as real event-driven transitions.
- **GEN Arena:** candidate comparison with net P&L after costs, trade count, drawdown, violations, champion eligibility and loss-autopsy links. Do not rank by gross P&L alone.
- **Market Scanner:** number scanned versus configured ceiling, data freshness, eligible instruments, skipped symbols and reason codes. Never imply that a scan ceiling is the actual number of available tradable contracts.
- **Risk & Execution Desk:** 6% notional limit, quantity/margin affordability, broker order/fill status, protective exits, reconciliation health, risk vetoes and halt reasons.
- **Research & Memory:** strategy versions, research findings, prior loss autopsies and replacement GEN inheritance trail.
- **Audit & Alerts:** timestamped decisions, errors, order lifecycle, service restarts, operator approvals and critical notifications.

### Data integrity and interactions
- All displayed states, metrics and connections must come from the backend/event stream or durable state. No fake live numbers, fake order events or simulated agent activity presented as real.
- Label paper/simulated data clearly. Show last update time and stale-data warnings.
- HQ must not itself enable live orders; the backend risk gate and separate operator approval remain authoritative.
- On refresh/restart, restore the actual durable state and reconcile broker state; never reset capital or invent a new GEN because the page reloaded.
- Test loading, empty, offline, stale, error and emergency-stop states, not only the attractive normal animation.
- Verify frontend source, backend integration, browser rendering and responsive layout before marking HQ complete.

## 10. Current implementation status (must be kept honest)

As of the current PR work:
- There is a foundation for MCX universe discovery, paper validation, GEN evolution, scorecards/loss retirement, Trading City/HQ state, and fail-closed live evidence gates.
- Recent CI workflows passed on the latest branch snapshot, but this is not live trading evidence.
- PR #57 remains open and calls out remaining HQ frontend verification and read-only Angel One paper validation.
- PR #58 is a draft master-specification PR; this specification documents requirements, not completed functionality.
- The complete end-to-end live GEN replacement loop, actual authorized Angel One account/feed validation, operational recovery, and Azure deployment must not be marked complete until verified by code/tests and operator-reviewed evidence.
- Live orders remain disabled.

## 11. Non-negotiable principles

1. ₹100 is the only initial capital; do not invent or reset funds.
2. Position notional is capped at 6% of current reconciled capital.
3. One active position at a time; reconcile before the next entry.
4. One-loss GEN retirement applies, but broker positions/orders must be handled safely.
5. Replacement must prove itself; it cannot auto-promote directly to live.
6. No trade is better than an invalid, unaffordable, or unsafe trade.
7. Profit is a goal, never a guarantee.
8. Safety controls survive every GEN retirement and process restart.
