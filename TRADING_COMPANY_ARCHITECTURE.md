# Trading Agent — Multi-Agent Trading Company

This layer adds a team-based architecture around the existing trading project.

## Core loop
Every 5 minutes:
1. Discover and refresh the supported market universe.
2. Evaluate up to 500–1000 markets when the configured data providers expose that many.
3. Estimate fair value, liquidity, spread, fees and slippage.
4. Flag candidate edge >= 8%.
5. Ask independent strategy agents to produce proposals.
6. Run an independent Bull/Bear/Quant/News/Social debate.
7. Apply Red-Team and Risk vetoes.
8. Size with conservative Kelly, capped at 6% of bankroll per position.
9. Execute only through an explicitly authorized adapter.
10. Record the decision and feed outcomes into post-trade diagnostics.

## Agents
- CEO / Orchestrator
- Broad Market Scanner
- Fair Value
- Momentum
- Mean Reversion
- Event Driven
- Crypto Specialist
- X/Social Research
- Cross-Market Arbitrage
- Bull Analyst
- Bear Analyst
- Quant Verifier
- Red Team
- Risk Manager
- Portfolio Manager
- Execution Agent
- Post-Trade Analyst
- Agent Health / Replacement Manager
- Treasury / Operating Budget
- Audit Logger

## Trade gate
A trade reaches execution only when:
- model confidence >= 0.80
- estimated edge >= 8%
- expected value remains positive after costs
- data is fresh
- liquidity is sufficient
- portfolio and daily-loss limits pass
- Red Team has no blocking objection

80% is a model score, not a guaranteed 80% win probability.

## Loss behavior
A losing trade never triggers a larger recovery trade by default.

The system:
- freezes repeated exposure to the same thesis
- diagnoses data/fair-value/regime/execution/liquidity errors
- creates a corrective research task
- permits another trade only if a fresh thesis passes the complete gate

## Agent lifecycle
ACTIVE -> DEGRADED -> QUARANTINED -> RETIRED

Track:
- calibration
- realized PnL contribution
- drawdown contribution
- data quality
- latency
- rule violations

A replacement agent must pass validation/backtest/simulation before activation.

## Treasury
Subscriptions must have an independent operating budget and hard spending cap. The system must not silently use remaining trading capital to pay bills.

When the operating budget is exhausted, optional paid services are disabled and the system enters a safe degraded state.

## Execution
Supported execution adapters can include:
- paper trading
- broker/exchange API
- authorized browser automation

Credentials must remain outside source control. Browser automation cannot bypass authentication, KYC, CAPTCHAs, account limits, or platform security.

## Reality check
No system can honestly guarantee profit, an 80% win rate, or successful execution on every market. The architecture is designed to maximize disciplined research and risk control rather than make unsupported profit guarantees.
