"""Trading City control-plane primitives.

This module is deliberately broker-agnostic and fail-closed. It describes
market-universe eligibility and a truthful HQ snapshot; it never places orders.
The live gate is always reported disabled here.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

CITY_SCHEMA_VERSION = 1
LIVE_TRADING_ENABLED = False
SCAN_INTERVAL_SECONDS = 300


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def build_market_universe(
    instruments: Iterable[Mapping[str, Any]],
    *,
    now: float | None = None,
    max_quote_age_seconds: float = 10.0,
    allowed_exchanges: tuple[str, ...] = ("MCX",),
) -> dict[str, Any]:
    """Filter a broker/public-feed instrument snapshot into eligible candidates.

    Required fields: symbol, exchange, quote_timestamp, last_price.
    Optional fields: instrument_type, lot_size, tradingsymbol.
    Missing or stale evidence is rejected, never guessed.
    """
    now = time.time() if now is None else float(now)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()

    for row in instruments:
        symbol = str(row.get("tradingsymbol") or row.get("symbol") or "").strip()
        exchange = str(row.get("exchange") or "").strip().upper()
        reason = ""
        if not symbol:
            reason = "MISSING_SYMBOL"
        elif symbol in seen:
            reason = "DUPLICATE_SYMBOL"
        elif exchange not in allowed_exchanges:
            reason = "EXCHANGE_NOT_ALLOWED"
        elif str(row.get("instrument_type") or "").upper() not in {"FUT", "FUTURE", "FUTURES"}:
            reason = "NOT_FUTURES"
        else:
            price = _number(row.get("last_price"))
            quote_ts = _number(row.get("quote_timestamp"))
            lot_size = _number(row.get("lot_size"))
            if price is None or price <= 0:
                reason = "INVALID_PRICE"
            elif quote_ts is None or quote_ts > now or now - quote_ts > max_quote_age_seconds:
                reason = "STALE_OR_MISSING_QUOTE"
            elif lot_size is None or lot_size <= 0 or not lot_size.is_integer():
                reason = "INVALID_LOT_SIZE"

        if reason:
            rejected.append({"symbol": symbol or "<missing>", "reason": reason})
            continue
        seen.add(symbol)
        accepted.append({
            "symbol": symbol,
            "exchange": exchange,
            "last_price": float(price),
            "quote_timestamp": float(quote_ts),
            "lot_size": int(lot_size),
        })

    return {
        "schema_version": CITY_SCHEMA_VERSION,
        "generated_at": now,
        "scan_interval_seconds": SCAN_INTERVAL_SECONDS,
        "eligible_count": len(accepted),
        "rejected_count": len(rejected),
        "eligible": accepted,
        "rejected": rejected,
        "live_trading_enabled": False,
    }


class TradingCity:
    """Small durable state registry used by runtime/HQ integrations."""

    def __init__(self, state_path: str | os.PathLike[str]):
        self.state_path = Path(state_path)
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if data.get("schema_version") != CITY_SCHEMA_VERSION:
                raise ValueError("unsupported city state schema")
            return data
        except FileNotFoundError:
            return self._empty()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # Corrupt state must not be treated as evidence of readiness.
            return self._empty(state_recovered=False)

    @staticmethod
    def _empty(*, state_recovered: bool = True) -> dict[str, Any]:
        return {
            "schema_version": CITY_SCHEMA_VERSION,
            "state_recovered": state_recovered,
            "updated_at": time.time(),
            "agents": {},
            "market_universe": {"eligible": [], "rejected": [], "eligible_count": 0},
            "tournament": {"stage": "GEN_TOURNAMENT", "champion_id": None, "status": "NOT_STARTED"},
            "validation": {"status": "NOT_STARTED", "broker": "Angel One", "read_only": True},
            "runtime": {"health": "INITIALIZING", "last_scan_at": None, "last_error": None},
            "risk": {"live_trading_enabled": False, "emergency_stop": True},
        }

    def register_agent(self, agent_id: str, role: str, status: str = "IDLE") -> None:
        if not agent_id.strip() or not role.strip():
            raise ValueError("agent_id and role are required")
        self.state["agents"][agent_id] = {
            "role": role.strip(),
            "status": status.strip().upper(),
            "updated_at": time.time(),
        }
        self._persist()

    def update_universe(self, snapshot: Mapping[str, Any]) -> None:
        if snapshot.get("live_trading_enabled") is not False:
            raise ValueError("universe snapshot must keep live trading disabled")
        self.state["market_universe"] = dict(snapshot)
        self.state["runtime"]["last_scan_at"] = snapshot.get("generated_at")
        self.state["runtime"]["health"] = "HEALTHY" if snapshot.get("eligible_count", 0) else "DEGRADED"
        self._persist()

    def update_tournament(self, *, stage: str, status: str, champion_id: str | None = None) -> None:
        if stage not in {"GEN_TOURNAMENT", "ANGELONE_PAPER_VALIDATION", "LIVE_CANDIDATE", "RETIRED"}:
            raise ValueError("unknown tournament stage")
        if stage == "LIVE_CANDIDATE" and status.upper() not in {"QUALIFIED", "READY_FOR_REVIEW"}:
            raise ValueError("live candidate must have an explicit qualified status")
        self.state["tournament"] = {
            "stage": stage,
            "status": status.upper(),
            "champion_id": champion_id,
            "updated_at": time.time(),
        }
        self._persist()

    def record_error(self, message: str) -> None:
        self.state["runtime"]["health"] = "DEGRADED"
        self.state["runtime"]["last_error"] = str(message)[:500]
        self._persist()

    def snapshot(self) -> dict[str, Any]:
        # Defensive copy so dashboard callers cannot mutate control-plane state.
        return json.loads(json.dumps(self.state))

    def _persist(self) -> None:
        self.state["updated_at"] = time.time()
        self.state["risk"]["live_trading_enabled"] = False
        self.state["risk"]["emergency_stop"] = True
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".city-", suffix=".tmp", dir=str(self.state_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.state, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.state_path)
        finally:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def sync_tournament_from_evolution(city: TradingCity, evolution: Mapping[str, Any]) -> dict[str, Any]:
    """Mirror a real GEN controller snapshot into City without advancing stages.

    This is intentionally paper-only: controller status is informational and
    can never promote a generation into Angel One validation or live trading.
    """
    status = str(evolution.get("status") or "RUNNING").strip().upper()
    champion_generation = evolution.get("champion_generation")
    champion_id = f"GEN-{champion_generation}" if champion_generation is not None else None
    city.update_tournament(
        stage="GEN_TOURNAMENT",
        status=status,
        champion_id=champion_id,
    )
    return {
        "status": status,
        "champion_generation": champion_generation,
        "result": evolution.get("result"),
        "deadline_at": evolution.get("deadline_at"),
        "session_generations": list(evolution.get("session_generations") or []),
        "next_stage": "ANGELONE_PAPER_VALIDATION" if status == "CHAMPION_RUNNING" else None,
        "live_trading_enabled": False,
    }
