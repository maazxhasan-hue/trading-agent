# Master Trading Agent Specification

Status: consolidated product specification. This document records the intended behavior; it is **not evidence that every feature is implemented or live-ready**. Track implementation through code, tests, paper validation, and an explicit operator approval.

## 1. Goal and venue

- Build an autonomous Indian-market trading agent using Angel One SmartAPI.
- Current target universe: Angel One instruments eligible for the selected Indian-market segments; prioritize supported cash-market instruments when affordable. MCX futures remain in scope only when actual contract lot size, margin, charges, and risk budget are affordable.
- Do not use Binance or crypto trading in the current live-trading plan.
- Discover the actual available instrument master at runtime. A scan ceiling of 1,000 markets is a ceiling, not a claim that 1,000 tradable contracts exist.
- Use continuous/event-driven market scanning while the market is open and data/API limits allow; a five-minute interval is not a mandatory wait between trades. Respect exchange trading hours, holidays, rate limits, and stale-data checks. The next trade may be considered only after the prior trade's final outcome and broker state are fully reconciled.

## 2. Capital, compounding, and trade sizing

- Starting live capital: ₹100, supplied by the operator.
- Milestone target: grow capital to ₹1,000 through compounding. This is an objective, not a promise or guaranteed return.
- One active trade/position at a time. Do not open a new entry until the previous trade's broker order/fill/position state has been reconciled.
- Maximum position notional: 6% of the latest reconciled available trading capital by default. This is a **position-value cap**, not 6% stop-loss risk. As verified net profits increase reconciled capital, the rupee value of this cap grows automatically; losses and charges reduce it. Do not raise the percentage or leverage merely because capital grew.
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
8. Only then begin a fresh decision cycle immediately when market/session/API conditions allow: refresh all required market/account data, rebuild the candidate list, collect new evidence, run the CEO-led adversarial debate and unanimous consensus, and re-check the backend risk gate. Do not reuse the previous trade's stale evidence or wait for a fixed five-minute timer solely because a trade just closed. If the prior result is unresolved or reconciliation is incomplete, do not open another trade.

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


## 10. Per-agent browser and evidence-first trading

### Dedicated browser workspace for every agent
- Every GEN/agent that performs market research must have its own isolated browser workspace, with a unique agent ID, profile/session storage, tabs, navigation history, research notes, and activity log. Use a separate headless Chrome/Chromium instance or a strongly isolated browser context/profile per agent, depending on the runtime's supported architecture; do not assume every agent needs a separately installed copy of the Chrome application.
- Browser sessions must not share cookies, authenticated sessions, local storage, or credentials across agents. Broker credentials and order-entry permissions must not be exposed to research browsers. Research agents are read-only by default.
- Show each agent's browser state in HQ: running/stopped, current page/domain, last navigation, research task, last evidence timestamp, and any blocked/error state. Never expose secrets, authentication tokens, or sensitive account details in the UI or logs.
- Browser automation must obey website terms, robots/access restrictions where applicable, rate limits, and safe browsing controls. Do not bypass CAPTCHAs, paywalls, access controls, or anti-bot protections. If a source is inaccessible, record that and use another permitted source.

### Evidence-first decision process (no random trades)
- No agent may recommend a trade merely because it was spawned, because a timer fired, or because it needs to hit a P&L target. A scan cycle may legitimately end with **NO TRADE**.
- For each candidate, collect a timestamped evidence packet before recommending it: instrument and venue, fresh price/quote and source, relevant price/volume/volatility history, spread/liquidity, market/session status, the specific strategy signal and its calculation, relevant permitted news/events if applicable, estimated fees/taxes/slippage, expected entry/exit logic, invalidation/stop conditions, position-size/margin check, and the reasons for rejecting stronger alternatives.
- Keep market facts separate from hypotheses and opinions. Store source URLs, retrieval timestamps, key extracted claims/observations, data freshness, and confidence/limitations so the decision can be audited and reproduced. Do not treat search-result snippets, social posts, or an LLM-generated summary alone as verified market data.
- Prefer authoritative broker/exchange instrument and quote data for price, trading status, contract specifications, and account/margin facts. Browser research can add context, but cannot override broker data, exchange rules, risk limits, or the backend's final eligibility checks.
- Require deterministic strategy/risk checks on structured data after research. A browser or language model may propose and explain a candidate, but it must never directly submit an order or bypass the single-position invariant, 6% position-notional cap, affordability checks, freshness checks, or operator approval.
- Before any paper/live candidate is accepted, the system must log: evidence packet ID, strategy/version, candidate score and calculation, risk-gate result, expected costs, decision explanation, and explicit trade/skip reason. For a skipped candidate, preserve reason codes (for example: stale data, weak signal, excessive spread, unaffordable lot/margin, missing evidence, session closed, or risk veto).
- If evidence is missing, contradictory, stale, not attributable to a source, or fails validation, the agent must abstain and request more evidence or return NO TRADE. Never fabricate a source, price, signal, confidence, browser action, or successful order.
- After every paper or closed live trade, compare the thesis with actual outcome, fees, slippage, and execution; save a loss/win autopsy and use it to inform future paper experiments. Learning may adjust hypotheses/parameters only through versioned, tested evaluation—not by silently changing live risk rules.

### Browser and evidence validation gates
- Tests must prove browser workspaces are isolated between two or more agents, restart safely, and cannot leak credentials or authenticated state.
- Tests must verify stale/missing/contradictory sources produce a skip, every trade recommendation has a complete evidence packet, and every skip has an auditable reason.
- Tests must confirm browser agents cannot submit broker orders and that only the existing backend risk/execution gate can authorize an order.
- The HQ may animate browser/network activity only from real telemetry. If a browser is stopped, disconnected, or has no fresh evidence, show that actual state rather than decorative activity.


## 12. CEO-led adversarial debate and consensus gate

### Debate before every trade candidate
- For each candidate trade, convene a logged debate led by the CEO/orchestrator. Required independent roles: Research, Quant/Strategy, Adversarial/Skeptic, Risk Officer, Portfolio/Capital, and Execution/Market-Data. Roles may be implemented as isolated agents or independently evaluated modules, but each must produce its own evidence-linked assessment before seeing the final consensus.
- The Research role presents sourced market context and evidence; Quant presents the reproducible signal, alternatives, and uncertainty; the Adversarial role must aggressively challenge the thesis and actively search for disconfirming evidence, counter-scenarios, and reasons the trade could fail; Risk checks hard limits and downside; Portfolio checks capital/position conflicts and affordability; Execution checks quote freshness, spread, liquidity, session, order constraints, and likely costs.
- The CEO must push for a substantive, critical debate—not rubber-stamp the first suggestion. Each role must be able to disagree, cite evidence, ask for more data, or vote NO TRADE. Record each role's reasoning, evidence packet references, vote, confidence/calibration where available, and unresolved objections in an immutable/auditable decision record.
- Use at least one debate/review round in which agents respond to the strongest opposing argument. If a material objection remains unresolved, evidence conflicts, required roles fail, or consensus is not reached within the configured time/data budget, the result is **NO TRADE** for that scan cycle. Never manufacture unanimity or force agents to agree.
- A trade proposal may proceed only when every required role explicitly votes APPROVE after reviewing the same current evidence packet and responding to material objections, and the independent deterministic backend risk gate also passes. Abstain, timeout, missing role, stale evidence, or any NO vote blocks the entry. CEO approval alone can never override a dissenting required role or a hard risk veto.
- Consensus applies to whether a candidate merits proceeding to the final risk/execution gate; it does not guarantee the trade will profit. Re-run the debate if material market data changes before execution, and reject the stale decision.
- Review alternatives and compare net expected value after fees, taxes/levies, spread and slippage, plus downside, invalidation conditions, and uncertainty. A candidate with no defensible evidence-backed edge must be rejected, even if all agents are enthusiastic.
- The consensus requirement does not relax the existing one-position rule, 6% maximum position-notional cap, affordability constraints, safe handling of open broker positions, one-loss GEN retirement policy, paper/validation promotion stages, or separate explicit operator authorization for live trading.

### CEO debate and consensus validation
- Unit/integration tests must cover unanimous approval, one dissenting vote, abstention, missing or timed-out agent, unresolved adversarial objection, conflicting/stale evidence, and a market-data change between consensus and order submission.
- Verify the system emits NO TRADE for every failed-consensus case and that the CEO cannot override a hard risk rejection.
- HQ must show each role's status and vote, evidence links, objection/rebuttal thread, debate round, final consensus result, backend risk-gate result, and the final trade/skip reason using real persisted events. Do not show invented debates or votes.
- Every decision must remain auditable after a GEN is retired, a replacement is spawned, or the process restarts.


## 13. Trade-to-trade cycle timing clarification (supersedes any ambiguous five-minute wording)

- The five-minute value is a possible market-scan/heartbeat cadence only; it is **not** a required cooldown or fixed interval between trades.
- Maintain continuous or event-driven scanning during supported market hours within API/data rate limits. Candidate discovery may run while a position is open, but no second position/order entry may be initiated until the current trade's final outcome is known and broker orders, fills, positions, and charges have been reconciled.
- Immediately after a trade is definitively closed and reconciled, start the next decision cycle: refresh live quotes and instrument/session data; fetch updated funds, positions, and order state; calculate the new reconciled capital and 6% cap; scan/re-rank candidates; gather fresh per-agent browser/evidence packets; conduct the full CEO-led adversarial debate; require every required role's explicit approval; then run the independent deterministic risk/execution gate.
- Execute the next trade only if every gate passes and a valid, affordable setup exists. Otherwise record **NO TRADE** with reasons and continue monitoring; never force a trade to meet a frequency or profit target.
- If a trade's result is not final, an order is partially filled/unknown, or broker reconciliation fails, stop new entries and reconcile first. Keep handling any existing position/protective orders safely.
- Tests must verify that a completed trade triggers a fresh next-cycle evaluation without a fixed five-minute cooldown, and that unresolved outcomes/reconciliation failures block new entries.


## 14. X (Twitter) intelligence and daily GEN improvement loop

### X intelligence collection
- When permitted access is configured, research agents should collect relevant public X posts and discussion context for the selected Indian-market instruments, companies, sectors, macro events, and market-moving announcements. Prefer official exchange/company/regulator accounts and original sources for factual claims.
- Respect X's current access/API terms, rate limits, privacy controls, and content restrictions. Use an authorized API or permitted access path; do not bypass login, rate limits, paywalls, CAPTCHAs, or platform restrictions. If X access is unavailable or quota-limited, log the limitation and continue with other permitted sources rather than inventing X data.
- Store source URL/post ID when available, author/account type, post and retrieval timestamps, extracted claim, topic/instrument mapping, and confidence/verification status. Distinguish original announcements from reposts, rumors, opinions, jokes, bots, and unverified claims. Avoid double-counting repeated/copied posts.
- Cross-check material claims against authoritative exchange filings, company announcements, regulator notices, broker/exchange data, or other credible sources. X sentiment is contextual evidence only; it is not a standalone buy/sell trigger and must never override structured price data, unanimous debate, the risk gate, or operator authorization.
- Detect spam/manipulation patterns, coordinated amplification, suspicious engagement, contradictory claims, and stale posts. When reliability is uncertain, lower confidence or exclude the signal and record why.
- Include X findings and source links in the per-trade evidence packet and CEO-led debate when relevant. If no trustworthy X information is available, explicitly record “no verified X signal”; do not fabricate a signal.

### Daily improvement and stronger-agent pipeline
- Run a daily scheduled improvement cycle that reviews all GENs' decisions, skipped opportunities, trade outcomes, evidence quality, debate objections, prediction calibration, fees/slippage, drawdowns, and rule violations.
- Generate versioned candidate improvements: strategy hypotheses, feature/data improvements, research prompts, debate quality checks, source reliability filters, execution simulations, and risk-model diagnostics. Preserve the prior version, experiment config, datasets/time windows, and rationale for every change.
- Evaluate candidates in isolated offline/backtest and out-of-sample tests, then paper tournaments with realistic fees, slippage, data latency, and market-session constraints. Prevent look-ahead bias, leakage between training and evaluation, and tuning only to recent wins.
- A candidate may be called “stronger” only if predeclared metrics show robust improvement against the incumbent across appropriate out-of-sample/paper samples, without violating drawdown, calibration, risk, or operational thresholds. Track uncertainty and minimum sample requirements; a single winning trade or one day's profit is not sufficient proof.
- Promote the best qualified candidate to paper/validation only. Daily creation, cloning, mutation, or retraining never grants live order permissions, extra capital, larger position limits, or the ability to bypass unanimous debate and risk gates. Live promotion still requires all existing validation stages and separate explicit operator approval.
- If no candidate passes, keep the current approved paper candidate unchanged and continue collecting evidence; do not force a daily replacement just to satisfy a schedule. The system should improve daily, but must not claim that each day's agent is objectively stronger without evidence.
- Preserve durable model/strategy versions, experiment results, rejected candidates and reasons, and rollback ability across process/VM restarts and GEN retirement.
- Tests must cover X access unavailable/rate-limited, duplicate/rumor/conflicting posts, source provenance, daily job failure/retry, no qualified candidate, out-of-sample leakage prevention, version rollback, and proof that new candidates cannot auto-enable live trading.


## 15. Capital-scaled opportunities and daily champion setup (safety clarification)

- As realized net profits increase the durable, broker-reconciled capital ledger, recalculate the rupee-denominated 6% position-notional cap from the new capital after every closed and reconciled trade. This lets the maximum affordable position value grow naturally with capital, without inventing funds or silently increasing the percentage cap.
- Evaluate all eligible candidates continuously during permitted market hours and rank them by a predeclared, evidence-backed quality score that considers signal strength, expected net edge after all costs, liquidity/spread, downside and invalidation, uncertainty, data freshness, and risk. The agents should seek the best valuable/high-conviction setup available, not merely the first signal.
- Each trading day, produce a “Daily Best Setup” report from the strongest eligible candidate(s), including the evidence packet, CEO debate, unanimous vote status, net-cost assumptions, downside scenarios, risk gate, and reasons alternatives were rejected. If an eligible setup passes all gates, it may be considered promptly; a closed and reconciled trade triggers a fresh evaluation without a mandatory five-minute cooldown.
- **Do not make a large trade mandatory.** There is no requirement to place one trade every day, to target a minimum profit per trade, to use the entire available risk budget, or to kill/retire an agent solely because no trade occurred that day. A day with no valid high-quality setup must end with NO TRADE. A strategy's daily activity is not a measure of skill.
- Never enlarge a position beyond the current 6% notional cap, exchange quantity/lot rules, actual available funds/margin, liquidity constraints, or any stricter risk gate. Do not use leverage, concentration, or loosened stops just to make a trade “big.” No setup can guarantee a large profit; a larger notional exposure can also increase losses and charges.
- Distinguish the configured one-loss GEN retirement rule from daily inactivity: a losing closed trade triggers the documented retirement/review procedure, but no-trade days do not. Retire or replace agents based on the explicitly configured policy and evidence, never to force daily activity.
- Tests must verify capital growth increases only the rupee amount of the 6% cap, losses/charges decrease reconciled capital, the system selects and reports the daily best setup when one exists, and no-trade days neither force orders nor trigger agent retirement.
