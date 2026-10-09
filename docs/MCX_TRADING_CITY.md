# MCX Trading City

## Purpose

Build an auditable, modular research and execution system for Angel One MCX futures. "City" means independent research roles with shared evidence and one central risk/execution authority; it does not mean independent agents may bypass the same account-level limits.

## Departments

- **Market intelligence:** load Angel One's MCX instrument master, retain supported futures contracts with valid tokens and non-expired expiries, collect fresh quotes, and report missing/stale data. `MCX_SYMBOL_FAMILIES=ALL` selects every supported MCX futures family. Options are intentionally excluded until their contract-specific risk, expiry, and order handling are separately validated.
- **Specialist research:** momentum/trend, mean reversion, event/macro context, commodity-specific analysis, volatility/regime analysis, and cross-market relationships. Specialists produce evidence and votes; they do not place orders.
- **Debate and red team:** challenge the proposed thesis, surface conflicting evidence, and reject low-confidence or regime-inconsistent setups.
- **GEN tournament:** compare candidate strategies using chronological out-of-sample validation, transaction costs, slippage, drawdown and stability. A high backtest return alone is not enough.
- **Risk office:** enforce account-level exposure, position-size, minimum-lot, available-funds/margin, stale-data, session, and drawdown limits. If a contract cannot fit the configured budget, skip it.
- **Execution and reconciliation:** one broker gateway owns idempotent order submission, fill confirmation, position reconciliation and emergency blocking. Research agents cannot bypass it.
- **Learning archive:** preserve forecasts, trade context, outcomes, and structured loss autopsies so successors inherit evidence rather than merely receiving a new name.

## One-loss replacement lifecycle

1. A losing **paper** trade retires the current paper generation.
2. The engine records instrument, side, entry/exit, P&L, exit reason, signal score/confidence, features, and specialist votes.
3. The next generation inherits the autopsy and existing learning history.
4. A replacement is a candidate, not automatically a better strategy. It must beat validation gates on unseen data before promotion.
5. A live loss must never trigger revenge trading, increased sizing, or an immediate untested strategy swap. Live generation retirement/promotion remains blocked until reliable live exit detection, persisted state, reconciliation, and paper/Angel One validation are implemented and verified.

## Scan scope and cadence

The configured scan ceiling is 1,000 returned instruments, and MCX mode evaluates every fetched instrument instead of truncating to 25. The actual universe is whatever Angel One returns for supported, non-expired MCX futures; 1,000 is a ceiling, not a guarantee that 1,000 contracts exist. The quote endpoint is rate-limited, so scan duration and history requests must be measured in the cloud before claiming a five-minute end-to-end cycle.

## Current limits

- Starting-capital/position sizing must match real contract lot sizes, margin, charges and funds. A ₹6 notional limit cannot be forced onto a futures contract whose minimum order is larger.
- The aspirational ₹1,000/hour target is not a guaranteed or validated return.
- This document and CI success do not enable live trading or deploy the service. Existing live approval gates must remain closed until exit handling, persistence/restart recovery, and broker reconciliation are independently verified.
