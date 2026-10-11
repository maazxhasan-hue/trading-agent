# Angel One SmartAPI login rate-limit design

Date: 2026-10-11

## Goal

Prevent redundant or uncontrolled SmartAPI authentication from trading-agent workers, make rate-limit failures visible as a safe `RATE_LIMITED` state, and provide read-only diagnostics. Preserve paper-only behavior. Do not bypass broker controls, deploy to the VM, or submit orders.

## Findings

### Confirmed

- The VM's recent error traceback goes through `AngelOneExecution._connect()` to the installed SDK's `generateSession()`. The SDK maps `api.login` to `/rest/auth/angelbroking/user/v1/loginByPassword`. The response body in the log is `Access denied because of exceeding access rate`. This is the login path, not the instrument-master download.
- The tracked `AngelOneExecution` constructor authenticates immediately when Angel One is enabled/read-only. Each NSE/MCX feed creates its own `AngelOneExecution`, while `NSETradingCompany` also creates an execution adapter. The VM's uncommitted multi-segment feed has the same pattern. A worker can therefore create duplicate clients and login requests.
- The VM has separate trading-agent processes active. The shared VM checkout also has uncommitted and untracked files, including the multi-segment entrypoint, which are absent from GitHub `main`; those changes must not be swept into this PR.
- VM egress currently matches the configured `ANGELONE_CLIENT_PUBLIC_IP` value `172.198.49.11`. This only confirms current value equality; it does not prove the egress is static or registered with Angel One.
- SmartAPI documentation says a login session remains active until midnight (unless logged out), and the `loginByPassword` endpoint is limited to one request per second. The docs do not specify a duration for the observed access-rate block.

### Root-cause assessment

The endpoint and failure are confirmed. Duplicate adapter construction and multiple worker processes create a credible path to concurrent or repeated login requests. That is the leading code-level cause, but the available evidence does not prove that it alone caused Angel One's response; a broker-side/account-level restriction or another client using the same account/IP remains possible. Support confirmation and a later operator-approved controlled test are needed to prove recovery.

## Design

1. Add an `AngelOneAuthManager` as the only owner of SmartAPI login/session refresh. Broker adapters and data feeds consume its shared client/session instead of independently authenticating.
2. Use a process-wide single-flight lock and a cross-process file lock. Under the process lock, re-read shared state so another worker's completed login is reused instead of repeated.
3. Persist the session metadata, cooldown, recent login-attempt budget, and last sanitized outcome in one configurable state file. Store session tokens only in that file with owner-only permissions (0600), atomically replace writes, and never include tokens in status or logs. Reuse login state only through the documented India-market-day expiry; use the documented token-generation flow only for a recognized expired-token response.
4. Enforce the documented one-request-per-second minimum interval, a configurable bounded login-attempt budget, and a configurable local cooldown. Honor a received `Retry-After` header. A 403 access-rate response immediately sets `RATE_LIMITED` and never triggers an automatic login retry. The configurable cooldown is a local circuit breaker, not an assertion about Angel One's block duration. Transient network failures use bounded exponential backoff with jitter within the attempt budget.
5. Capture timestamp, endpoint path, status when available, sanitized error category, correlation ID when supplied, attempt count, and remaining cooldown. Do not log request bodies, headers, tokens, PIN/TOTP, cookies, or raw SDK exceptions. The adapter reports `RATE_LIMITED` without initiating login from status/health reads.
6. Add a read-only VM diagnostic script that reports service/process state, current and configured public IP (and whether they match), sanitized recent login errors, and persisted cooldown state. It must not print configuration values other than the public IP or make Angel One requests.
7. Keep `LIVE_TRADING=false` and `ANGELONE_READONLY=true`; never add a test-order path. Add automated tests for duplicate logins under concurrency, repeated 403/cooldown persistence, session reuse, bounded transient retries, secret/header redaction, and safe reported status.

## Scope and validation

- Implement on `codex/angelone-auth-rate-limit`, based on repository `main`, without importing the VM's unrelated working-tree edits.
- Run focused auth tests, the repository's pytest and unittest CI commands, Python compilation, and dashboard syntax checks when applicable.
- Do not start, stop, reconfigure, or deploy to the Azure VM. Do not call the Angel One login endpoint during implementation or verification.
- After the cooldown is believed clear and support confirms the account/IP state, request operator approval before any single controlled authentication test.
- Do not claim recovery until that controlled test succeeds.
