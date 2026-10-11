# Angel One SmartAPI Login Rate-Limit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Centralize SmartAPI authentication so broker workers reuse one valid session, stop safely on 403 rate limits, and expose sanitized authentication status and diagnostics.

**Architecture:** Add an auth manager that owns login, documented token refresh, cross-thread and cross-process coordination, and protected persisted session/cooldown state. Adapt existing brokers and service status to read the manager's state without causing logins, then add a read-only VM diagnostic command.

**Tech Stack:** Python 3.12, SmartAPI Python SDK, standard-library threading/file locks/JSON, requests, pytest and unittest.

**Spec:** `docs/superpowers/specs/2026-10-11-angelone-auth-rate-limit-design.md`

## Global Constraints

- Store shared session state with owner-only permissions (0600); never write tokens to repository files.
- Enforce at least one second between `loginByPassword` requests.
- Keep `LIVE_TRADING=false` and `ANGELONE_READONLY=true`; never place a test order.
- Do not start, stop, reconfigure, or deploy to the Azure VM; do not call Angel One during implementation or verification.
- A 403 access-rate response sets persistent `RATE_LIMITED` state and does not retry automatically.
- Never log request bodies, headers, tokens, PIN/TOTP, cookies, or raw SDK exceptions.

## Review Focus

- Corrupt or incomplete persisted state must fail closed without printing token material; test malformed JSON and missing token fields.
- `Retry-After` may be seconds or an HTTP date and may be invalid; test valid values and fallback to the local circuit-breaker cooldown.
- India-market-day expiry is a timezone boundary; test session reuse just before midnight and expiry at/after midnight Asia/Kolkata.
- State-file permission or atomic-write failures must not start a second login; test write failure leaves status blocked and secrets absent from logs.
- Invalid retry/cooldown configuration must be bounded and must never lower the one-second documented login interval; test zero, negative, and malformed values.

---

### Task 1: Implement the shared auth manager and persistence

**Files:**
- Create: `angelone_auth.py`
- Create: `tests/test_angelone_auth_manager.py`

**Interfaces:**
- Produces: `AngelOneAuthManager.get_client() -> SmartConnect`, `AngelOneAuthManager.status() -> dict`, and `AngelOneAuthManager.handle_expired_session() -> SmartConnect`.
- Produces: a test-injectable auth transport that returns HTTP status, response headers, and parsed response data without logging raw request/response contents.

- [ ] **Step 1: Write failing tests** named `test_rate_limit_403_enters_cooldown_without_retry`, `test_cooldown_survives_manager_restart`, `test_concurrent_processes_share_one_login`, `test_valid_session_is_reused_until_india_midnight`, `test_expired_jwt_uses_documented_refresh_once`, `test_transient_network_failures_use_bounded_backoff`, `test_state_file_is_private_and_atomic`, and `test_auth_event_redacts_credentials_and_headers`. Inject clock, sleeper, jitter, state path, and transport; assert request counts, state, status, and captured logs.
- [ ] **Step 2: Run the focused tests and confirm they fail** because `AngelOneAuthManager` and its state/transport behavior do not exist.
- [ ] **Step 3: Implement `AuthSettings`, `AuthTransport`, `AngelOneAuthManager`, and safe state read/write** in `angelone_auth.py`. Use a thread lock plus an OS file lock; after acquiring the process lock, reload state before deciding whether login is necessary. Persist session tokens, India session date, attempt timestamps, cooldown deadline, and sanitized last outcome in a configurable JSON state file. Create/update it atomically with mode 0600. Reuse session data through midnight Asia/Kolkata; refresh only on a recognized expired-token response. On access-rate 403, persist `RATE_LIMITED`, honor `Retry-After` when present, otherwise apply only the configured local cooldown, and make no automatic retry. Bound transient retries and the attempt budget.
- [ ] **Step 4: Run the focused tests and confirm they pass**, including two independent processes racing on the same state file and restart-based cooldown/session reuse.
- [ ] **Step 5: Commit** as `feat: centralize Angel One authentication`.

### Task 2: Route all Angel One adapters through the manager

**Files:**
- Modify: `angelone_adapter.py`
- Modify: `angelone_market_data.py`
- Modify: `angelone_mcx_market_data.py`
- Modify: `nse_agent.py`
- Modify: `tests/test_angelone_adapter.py`
- Create: `tests/test_angelone_auth_wiring.py`

**Interfaces:**
- Consumes: `AngelOneAuthManager.get_client()`, `status()`, and `handle_expired_session()` from Task 1.
- Produces: one shared manager/client per configuration; adapter status includes `auth_status` and `cooldown_remaining_seconds`. Feed constructors accept an optional broker for explicit reuse.

- [ ] **Step 1: Write failing tests** named `test_multiple_adapters_share_one_session`, `test_feed_reuses_injected_broker`, `test_status_reads_do_not_login`, `test_rate_limited_adapter_fails_closed`, and `test_sdk_logs_never_emit_auth_material`. Assert one login for multiple feed/execution adapters, no login from `status()`, and no order calls.
- [ ] **Step 2: Run those tests and confirm they fail** because constructors currently authenticate independently and status does not expose blocked auth state.
- [ ] **Step 3: Integrate the manager** in `AngelOneExecution`; keep login out of quote/history/instrument scan paths, reuse the shared client, and surface `RATE_LIMITED` without logging raw SDK exceptions. Disable or sanitize SmartAPI SDK logging before any request. Allow both feeds to receive the already-created broker and update `NSETradingCompany` to create/pass one adapter for Angel One backends.
- [ ] **Step 4: Run focused adapter/wiring tests and confirm they pass** with all order methods mocked and asserted unused.
- [ ] **Step 5: Commit** as `fix: reuse Angel One sessions across adapters`.

### Task 3: Expose safe auth status in the service API

**Files:**
- Modify: `agent_supervisor.py`
- Create: `tests/test_agent_supervisor_auth_status.py`

**Interfaces:**
- Consumes: read-only `AngelOneAuthManager.status()`.
- Produces: `/health` and `/metrics` report `broker_auth.status` as `AUTHENTICATED`, `AUTH_REQUIRED`, `RATE_LIMITED`, or `UNAVAILABLE`, plus cooldown seconds where applicable. Reading status never initializes an auth request.

- [ ] **Step 1: Write failing tests** named `test_health_reports_rate_limited_without_login` and `test_metrics_do_not_expose_tokens_or_credentials`.
- [ ] **Step 2: Run them and confirm they fail** because supervisor health currently reports only generic service health.
- [ ] **Step 3: Add read-only auth status** to supervisor health/metrics; avoid importing or constructing `AngelOneExecution` from a health request.
- [ ] **Step 4: Run the focused supervisor tests and confirm they pass**, including assertions that login transport and secret values are untouched.
- [ ] **Step 5: Commit** as `feat: report Angel One auth status safely`.

### Task 4: Add the read-only VM diagnostic command and operator docs

**Files:**
- Create: `scripts/diagnose_angelone_auth.py`
- Create: `docs/ANGELONE_AUTH_DIAGNOSTICS.md`
- Create: `tests/test_angelone_diagnostics.py`

**Interfaces:**
- Produces: `python scripts/diagnose_angelone_auth.py` prints relevant service states, matching process counts, configured/current egress IP and match status, sanitized recent auth errors, and persisted cooldown state. It reads local files/system status and may query the public IP service, but never calls Angel One or prints credential values.
- Produces: operator documentation for the command, state-file location/configuration, cooldown interpretation, and the requirement for explicit approval before one later login test.

- [ ] **Step 1: Write failing tests** named `test_diagnostics_redact_env_and_log_secrets`, `test_diagnostics_report_ip_and_cooldown`, and `test_diagnostics_never_calls_smartapi`; inject filesystem, process/systemd, and public-IP readers.
- [ ] **Step 2: Run them and confirm they fail** because the diagnostic script and documentation do not exist.
- [ ] **Step 3: Implement the read-only diagnostic and docs**; keep service/process output to names/counts, normalize recent error messages to safe categories, and show only the configured/current public IP values and comparison.
- [ ] **Step 4: Run focused diagnostic tests and confirm they pass** with synthetic logs containing fake API key, PIN, TOTP, JWT, refresh token, cookie, and authorization-header values.
- [ ] **Step 5: Commit** as `feat: add safe Angel One diagnostics`.

### Task 5: Run repository checks and prepare the PR

**Files:**
- Modify: `.github/workflows/ci.yml` only if needed to exercise the new test suite; otherwise no CI-file change.

**Interfaces:**
- Consumes: completed Tasks 1–4.
- Produces: validated branch `codex/angelone-auth-rate-limit` and an open PR targeting `main`; no merge or deployment.

- [ ] **Step 1: Run focused tests**: `python -m pytest tests/test_angelone_auth_manager.py tests/test_angelone_adapter.py tests/test_angelone_auth_wiring.py tests/test_agent_supervisor_auth_status.py tests/test_angelone_diagnostics.py -q`. Expected: all pass.
- [ ] **Step 2: Run all repository checks**: `python -m pytest -q`, `python -m unittest discover -s tests -v`, `python -m compileall -q .`, and the Node syntax checks in `.github/workflows/ci.yml`. Run configured lint/type checks if the repository defines them; record if none are configured.
- [ ] **Step 3: Inspect the final diff** for accidental VM files, secrets, logs, generated state, unsafe retries, and any changes to live-trading flags. Confirm no test or command contacted Angel One.
- [ ] **Step 4: Open the PR** with confirmed findings, the residual root-cause uncertainty, test results, safe operator command, and the manual support/approval step. Leave the PR open, unmerged, and undeployed.
