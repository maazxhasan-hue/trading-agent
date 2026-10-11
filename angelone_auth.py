"""Cross-process, fail-closed SmartAPI authentication state manager.

The transport and client factory are injected so tests never contact Angel One.
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

log = logging.getLogger("angelone.auth")
_LOGIN_PATH = "/rest/auth/angelbroking/user/v1/loginByPassword"
_REFRESH_PATH = "/rest/auth/angelbroking/jwt/v1/generateTokens"
_lock_local = threading.local()


class AuthBlocked(RuntimeError):
    """Authentication is unavailable or locally rate limited."""


@dataclass(frozen=True)
class AuthResponse:
    status_code: int
    headers: dict[str, str]
    data: dict[str, Any]


@dataclass
class AuthSettings:
    state_path: Path = field(default_factory=lambda: Path(os.getenv("ANGELONE_AUTH_STATE_PATH", "/var/lib/trading-agent/angelone-auth.json")))
    cooldown_seconds: float = 900
    min_interval_seconds: float = 1
    max_attempts: int = 3
    max_backoff_seconds: float = 30


class AngelOneAuthManager:
    def __init__(self, settings: AuthSettings | None = None, transport: Callable[[], AuthResponse] | None = None,
                 client_factory: Callable[[dict[str, Any]], Any] | None = None, clock: Callable[[], datetime] | None = None,
                 sleeper: Callable[[float], None] = time.sleep, jitter: Callable[[], float] = random.random,
                 refresh_transport: Callable[[dict[str, Any]], AuthResponse] | None = None):
        self.settings = settings or AuthSettings()
        self.settings.min_interval_seconds = max(1.0, float(self.settings.min_interval_seconds))
        self.settings.max_attempts = min(5, max(1, int(self.settings.max_attempts)))
        self.settings.cooldown_seconds = min(86400, max(1, float(self.settings.cooldown_seconds)))
        self.settings.max_backoff_seconds = min(300, max(1, float(self.settings.max_backoff_seconds)))
        self.transport = transport or self._environment_transport
        self.refresh_transport = refresh_transport
        self.client_factory = client_factory or (lambda session: session)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleeper, self.jitter = sleeper, jitter
        self._thread_lock = threading.RLock()
        self._client = None
        self._client_jwt = None

    def _now(self):
        value = self.clock()
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    @contextmanager
    def _process_lock(self, create=True):
        parent = self.settings.state_path.parent
        lock_path = str(self.settings.state_path) + ".lock"
        if create:
            parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        elif not parent.exists() or not Path(lock_path).exists():
            # A read-only status query must not create directories or lock files.
            yield
            return
        held = getattr(_lock_local, "held", set())
        if lock_path in held:
            yield
            return
        fd = os.open(lock_path, (os.O_CREAT | os.O_RDWR if create else os.O_RDWR), 0o600)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX)
            _lock_local.held = {*held, lock_path}
            yield
        finally:
            _lock_local.held = held
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read(self):
        try:
            state = json.loads(self.settings.state_path.read_text())
            if not isinstance(state, dict):
                return {}
            return state
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return {"state": "UNAVAILABLE", "last_event": {"category": "INVALID_STATE"}}

    def _write(self, state):
        path = self.settings.state_path
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(state, stream, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            os.chmod(path, 0o600)
        finally:
            try:
                os.unlink(temp)
            except FileNotFoundError:
                pass

    def _session_valid(self, state):
        session = state.get("session")
        if not isinstance(session, dict) or not all(session.get(k) for k in ("jwtToken", "refreshToken", "feedToken")):
            return False
        try:
            expires = datetime.fromisoformat(state.get("session_expires_at", ""))
            return self._now() < expires
        except (TypeError, ValueError):
            return False

    def _session_client(self, state):
        jwt = state["session"]["jwtToken"]
        if self._client is None or self._client_jwt != jwt:
            self._client = self.client_factory(dict(state["session"]))
            self._client_jwt = jwt
        return self._client

    def status(self):
        with self._thread_lock, self._process_lock(create=False):
            state = self._read()
            cooldown = max(0, float(state.get("cooldown_until", 0)) - self._now().timestamp())
            if state.get("state") == "RATE_LIMITED" and cooldown:
                status = "RATE_LIMITED"
            elif state.get("state") == "UNAVAILABLE" or (state.get("session") and not self._session_valid(state) and not state.get("session_expires_at")):
                status = "UNAVAILABLE"
            elif self._session_valid(state):
                status = "AUTHENTICATED"
            else:
                status = "AUTH_REQUIRED"
            return {"status": status, "cooldown_remaining_seconds": math.ceil(cooldown), "last_event": state.get("last_event")}

    def get_client(self):
        with self._thread_lock, self._process_lock():
            state = self._read()
            now = self._now()
            if state.get("state") == "UNAVAILABLE":
                raise AuthBlocked("Angel One authentication state is unavailable.")
            if state.get("session"):
                if not all(state["session"].get(k) for k in ("jwtToken", "refreshToken", "feedToken")):
                    raise AuthBlocked("Angel One persisted session state is incomplete.")
                try:
                    datetime.fromisoformat(state.get("session_expires_at", ""))
                except (TypeError, ValueError):
                    raise AuthBlocked("Angel One persisted session state is incomplete.") from None
            if state.get("state") == "RATE_LIMITED" and float(state.get("cooldown_until", 0)) > now.timestamp():
                raise AuthBlocked("Angel One authentication is rate limited.")
            if self._session_valid(state):
                return self._session_client(state)
            attempts = [float(x) for x in state.get("attempts", []) if now.timestamp() - float(x) < 86400]
            if len(attempts) >= self.settings.max_attempts:
                self._persist_block(state, now.timestamp() + self.settings.cooldown_seconds, "ATTEMPT_BUDGET")
                raise AuthBlocked("Angel One authentication attempt budget exhausted.")
            previous = max(attempts, default=0)
            if previous and now.timestamp() - previous < self.settings.min_interval_seconds:
                self.sleeper(self.settings.min_interval_seconds - (now.timestamp() - previous))
            attempts.append(now.timestamp())
            state["attempts"] = attempts
            # Persist reservation before network I/O so restarts/processes cannot
            # spend the same login budget or race another credential attempt.
            self._write({**state, "state": "AUTH_REQUIRED"})
            try:
                response = self.transport()
            except Exception:
                self._write({**state, "state": "AUTH_REQUIRED", "last_event": self._event(None, "NETWORK_ERROR", len(attempts))})
                if len(attempts) >= self.settings.max_attempts:
                    raise AuthBlocked("Angel One authentication failed; attempt budget exhausted.") from None
                delay = min(self.settings.max_backoff_seconds, 2 ** (len(attempts) - 1)) * (0.5 + max(0, min(1, self.jitter())))
                self.sleeper(delay)
                return self.get_client()
            if response.status_code == 403:
                retry = self._retry_after(response.headers, now)
                cooldown = retry if retry is not None else now.timestamp() + self.settings.cooldown_seconds
                message = str(response.data.get("message", "")).lower()
                category = "HTTP_403_RATE_LIMITED" if "rate" in message else "HTTP_403_ACCESS_DENIED"
                self._persist_block({**state, "attempts": attempts}, cooldown, category, 403, response.headers)
                raise AuthBlocked("Angel One authentication is rate limited.")
            if response.status_code < 200 or response.status_code >= 300 or not response.data.get("status"):
                event = self._event(response.status_code, "AUTH_REJECTED", len(attempts), response.headers)
                self._write({**state, "attempts": attempts, "state": "AUTH_REQUIRED", "last_event": event})
                raise AuthBlocked("Angel One authentication was rejected.")
            tokens = response.data.get("data") or {}
            if not all(tokens.get(k) for k in ("jwtToken", "refreshToken", "feedToken")):
                self._write({**state, "state": "UNAVAILABLE", "last_event": self._event(response.status_code, "INCOMPLETE_SESSION", len(attempts))})
                raise AuthBlocked("Angel One returned an incomplete session.")
            india_day = now.astimezone(ZoneInfo("Asia/Kolkata")).date()
            expires = datetime.combine(india_day, datetime.max.time(), ZoneInfo("Asia/Kolkata")).isoformat()
            state = {"session": {k: tokens[k] for k in ("jwtToken", "refreshToken", "feedToken")},
                     "session_expires_at": expires, "session_day": india_day.isoformat(), "attempts": attempts,
                     "state": "AUTHENTICATED", "cooldown_until": 0,
                     "last_event": self._event(response.status_code, "AUTHENTICATED", len(attempts), response.headers)}
            self._write(state)
            self._client = self.client_factory(dict(state["session"]))
            self._client_jwt = state["session"]["jwtToken"]
            return self._client

    def handle_expired_session(self, rejected_token=None):
        """Refresh one recognized expired JWT using SmartAPI's generateTokens flow."""
        with self._thread_lock, self._process_lock():
            state = self._read()
            if state.get("state") == "UNAVAILABLE":
                raise AuthBlocked("Angel One session refresh is unavailable.")
            if state.get("state") == "RATE_LIMITED" and float(state.get("cooldown_until", 0)) > self._now().timestamp():
                raise AuthBlocked("Angel One authentication is rate limited.")
            session = state.get("session") or {}
            if rejected_token and session.get("jwtToken") and session.get("jwtToken") != rejected_token:
                return self._session_client(state)
            if not session.get("refreshToken") or self.refresh_transport is None:
                raise AuthBlocked("Angel One session refresh is unavailable.")
            try:
                response = self.refresh_transport(dict(session))
            except Exception:
                self._write({**state, "state": "UNAVAILABLE", "last_event": self._event(None, "REFRESH_NETWORK_ERROR", 0, endpoint=_REFRESH_PATH)})
                raise AuthBlocked("Angel One session refresh failed.") from None
            data = response.data.get("data") or {}
            if response.status_code == 403:
                now = self._now()
                retry = self._retry_after(response.headers, now)
                cooldown = retry if retry is not None else now.timestamp() + self.settings.cooldown_seconds
                self._persist_block(state, cooldown, "REFRESH_HTTP_403", 403, response.headers, endpoint=_REFRESH_PATH)
                raise AuthBlocked("Angel One authentication is rate limited.")
            if response.status_code < 200 or response.status_code >= 300 or not response.data.get("status") or not data.get("jwtToken") or not data.get("feedToken"):
                self._write({**state, "state": "UNAVAILABLE", "last_event": self._event(response.status_code, "REFRESH_REJECTED", 0, response.headers, endpoint=_REFRESH_PATH)})
                raise AuthBlocked("Angel One session refresh was rejected.")
            renewed = {"jwtToken": data["jwtToken"], "refreshToken": data.get("refreshToken") or session["refreshToken"], "feedToken": data["feedToken"]}
            day = self._now().astimezone(ZoneInfo("Asia/Kolkata")).date()
            expiry = datetime.combine(day, datetime.max.time(), ZoneInfo("Asia/Kolkata")).isoformat()
            state.update({"session": renewed, "session_day": day.isoformat(), "session_expires_at": expiry,
                          "state": "AUTHENTICATED", "cooldown_until": 0,
                          "last_event": self._event(response.status_code, "SESSION_REFRESHED", 0, response.headers, endpoint=_REFRESH_PATH)})
            self._write(state)
            self._client = self.client_factory(dict(renewed))
            self._client_jwt = renewed["jwtToken"]
            return self._client

    def _persist_block(self, state, until, category, status=403, headers=None, endpoint=_LOGIN_PATH):
        state.update({"state": "RATE_LIMITED", "cooldown_until": until,
                      "last_event": self._event(status, category, len(state.get("attempts", [])), headers, endpoint=endpoint)})
        self._write(state)

    def _event(self, status, category, attempts, headers=None, endpoint=_LOGIN_PATH):
        headers = headers or {}
        correlation = headers.get("x-request-id") or headers.get("X-Request-ID")
        if correlation and not (len(correlation) <= 80 and all(c.isalnum() or c in "-" for c in correlation)):
            correlation = None
        return {"timestamp": self._now().isoformat(), "endpoint": endpoint, "status": status,
                "category": category, "correlation_id": correlation, "attempts": attempts}

    def _retry_after(self, headers, now):
        value = headers.get("Retry-After") or headers.get("retry-after")
        if not value:
            return None
        try:
            return now.timestamp() + min(86400, max(1, float(value)))
        except (ValueError, TypeError):
            try:
                return min(now.timestamp() + 86400, parsedate_to_datetime(value).timestamp())
            except (ValueError, TypeError, OverflowError):
                return None

    def _environment_transport(self):
        """Production login transport is injected by the adapter; fail closed by default."""
        raise AuthBlocked("Angel One authentication transport is not configured.")


def read_auth_status():
    """Read persisted broker auth state without initializing an API request."""
    manager = AngelOneAuthManager(settings=AuthSettings(), transport=lambda: None)
    return manager.status()
