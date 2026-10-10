# Trading City HQ — Individual Agent Observatory

## Product requirement

Every configured logical agent must have its own inspectable identity and detail page inside Trading City HQ. The operator must be able to select any agent individually and see what it is responsible for, what it has actually researched, what it knows and does not know, which agents it exchanged evidence with, what it recommended, how other agents challenged it, and what measurable outcomes resulted.

This document is a requirements contract. Do not claim the HQ already renders these views until the frontend is located, wired to runtime APIs, and verified with tests/screenshots. Never generate fake agent activity to make the HQ look alive.

## Required HQ screens

### 1. Company overview
- Counts of configured, connected, healthy, degraded, quarantined, retired, and currently active agents as distinct statuses.
- Current cycle ID, last successful cycle, last data refresh, market session/provider status, paper/live mode, and global kill-switch state.
- A live collaboration graph whose nodes and edges come from real registry heartbeats and message-bus events.
- Clear system-wide blockers and why a trade was rejected or no trade was taken.
- Separate actual positions/orders/balances from estimates and simulated paper state.

### 2. Agent directory
- Search/filter by name, role, strategy, status, market/venue, and last-seen time.
- Each agent has a unique stable ID, display name, role, version, owner/supervisor, status, heartbeat, last successful run, current task/cycle, and required/optional classification.
- Clicking any agent opens its individual detail page. No hidden roster entries.

### 3. Individual agent page (required for every agent)
Show:
1. Identity, mission, responsibilities, allowed actions, prohibited actions, strategy/market scope, version, and status.
2. What the agent is doing now, task start/update time, cycle ID, runtime/latency, and last heartbeat. If it is not running, say so plainly.
3. **Research ledger:** every source actually accessed, provider/domain, source URL or stable ID, source timestamp, retrieval time, freshness/expiry, key claims, evidence excerpt/summary, confidence and uncertainty, and source-access errors. Never fabricate source records.
4. Information received from other agents, information sent to other agents, message IDs, dependencies, timestamps, and whether messages were acknowledged.
5. Findings and recommendations, supporting evidence, contradictory evidence, assumptions, unresolved questions, and what would invalidate the conclusion.
6. Debate record: votes (approve/reject/abstain), reasoning, objections raised, response to objections, and final disposition.
7. Strategy/model version, evaluation sample size, calibration, walk-forward and paper results, drawdown/PnL attribution where measured, and last validation time. Clearly mark unavailable metrics as unavailable, not zero.
8. Errors, retries, rate limits, degraded connectors, quarantine history, and corrective tasks.
9. Audit timeline and links to the cycle, evidence packets, risk verdict, order/reconciliation, and post-trade review.
10. Controls limited to safe operations: pause/resume research, request a re-run, open evidence, compare versions, and quarantine a faulty agent. Live order approval or credential display must not be exposed through research-agent controls.

### 4. Collaboration / evidence explorer
- Browse cycle IDs and the full evidence lineage from source -> specialist -> quant -> debate -> risk -> decision -> execution/reconciliation -> post-trade.
- Filter by instrument, source, agent, timestamp, decision, and veto reason.
- Show duplicate/related sources so repeated copies of one rumor do not masquerade as independent confirmation.
- Display disagreements and missing inputs explicitly.

### 5. Agent comparison and GEN Arena
- Compare agents/candidates on the same time window and instrument universe.
- Show sample size, benchmark, out-of-sample/walk-forward results, calibration, transaction costs, slippage, drawdown and confidence intervals where available.
- Promote only after predeclared validation gates pass; retain incumbent and rollback.
- Distinguish a strategy candidate (GEN) from a running worker process and from a logical role.

### 6. Decision, execution and audit views
- Show the complete vote matrix and veto reasons for each decision.
- Risk gate and operator live-arming state remain separate from CEO recommendation.
- Order status must come from venue/broker evidence; unknown or unreconciled order state blocks additional exposure.
- Keep paper trades visually distinct from live orders and mark the mode on every relevant panel.

## Canonical runtime data contracts

Implement typed/versioned APIs or equivalent schemas for:
- `AgentDefinition`: stable ID, name, role, responsibilities, allowed tools/actions, market scope, required flag, version.
- `AgentHeartbeat`: agent ID, status, observed_at, last_success_at, current_task, cycle ID, latency, error/degraded reason.
- `AgentMessage`: message ID, schema version, sender/recipient IDs, cycle ID, created/expiry times, message type, evidence references, acknowledgement state.
- `EvidenceRecord`: evidence ID, source/provider, URL/stable source ID, published/source time, retrieved time, expires time, content hash, claims, confidence, limitations, access status.
- `AgentRun`: run ID, agent ID/version, cycle ID, input/output references, start/end, result, error, resource/latency metrics.
- `AgentAssessment`: thesis, assumptions, supporting/contradicting evidence, uncertainty, invalidation conditions, vote, objections.
- `DecisionRecord`: cycle ID, instrument, mode, votes, risk verdict, vetoes, chosen/no-trade reason, linked order/reconciliation IDs.
- `AgentEvaluation`: benchmark, sample size, dates, in/out-of-sample metrics, calibration, costs, drawdown, validation decision.
- `AuditEvent`: append-only actor/action/target/time, previous and new state, reason, correlation ID.

All timestamps are UTC ISO-8601. Preserve source timestamps separately from retrieval time. Unknown values remain null/unknown; do not substitute zero or fabricate a heartbeat. Use pagination, retention limits, and access control for large research histories.

## Data access and privacy boundaries

- Research agents are read-only and receive no broker credentials, wallet secrets, or order permissions.
- Secret values must never be sent to the browser or stored in evidence packets/logs.
- Respect provider terms, API scopes, rate limits, robots/access controls, and platform authentication. No CAPTCHA/security bypass.
- X/social data must include source provenance and be cross-checked; distinguish public access from authorized API access.
- Audit data is append-only for ordinary agents. Corrections are new linked events, not silent rewrites.
- Operator controls require authentication and authorization; dangerous actions need confirmation and explicit audit entries.

## Acceptance criteria

1. The directory is generated from the runtime registry, not a hard-coded decorative list.
2. Every configured role has a unique detail route and displays its mission even when it has never run.
3. Never-run agents show `NOT RUN / NO DATA`; disconnected agents show last-seen time and reason.
4. The source ledger contains only real connector responses and verifiable source references.
5. Agent-to-agent communication edges appear only when actual message events exist.
6. A user can open a decision and trace each material claim back to its evidence source.
7. Stale, missing, duplicate, or conflicting evidence is visibly flagged.
8. Paper and live data are impossible to confuse; live remains disabled by default until separately approved.
9. Empty/error/loading states and authorization failures are tested.
10. CI includes schema, API, frontend, and integration tests; a documented smoke test verifies each screen against a real paper-mode runtime.
11. HQ must not claim all agents are connected/active merely because they are listed in YAML.
12. If the backend is offline, show last known state and a prominent stale/offline indicator instead of simulated activity.

## Implementation order

1. Inspect the existing HQ/front-end and runtime registry before creating new components.
2. Add registry and typed telemetry endpoints/adapters, reusing existing code rather than building a duplicate system.
3. Implement directory and reusable individual-agent page.
4. Add evidence ledger, collaboration explorer, debate/risk trace, and GEN comparison.
5. Wire actual runtime events and broker/paper reconciliation data.
6. Add tests, run CI, and verify screenshots against actual runtime responses.
7. Only then mark the HQ implementation complete. Live deployment/order execution is a separate approval.
