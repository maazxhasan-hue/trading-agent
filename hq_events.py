"""Small, dependency-free event bridge from the trading engine to Trading Agent HQ.

The engine writes newline-delimited JSON to a local file. The dashboard server
tails that file and exposes it as Server-Sent Events. This keeps the trading
engine independent from the web UI and contains no broker credentials.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

EVENT_FILE = Path(os.getenv("HQ_EVENT_FILE", "data/hq_events.jsonl"))
_MAX_BYTES = int(os.getenv("HQ_MAX_EVENT_FILE_BYTES", "5242880"))
_LOCK = threading.Lock()


def _trim_if_needed() -> None:
    try:
        if EVENT_FILE.stat().st_size <= _MAX_BYTES:
            return
        lines = EVENT_FILE.read_text(encoding="utf-8").splitlines()
        keep = lines[-2000:]
        tmp = EVENT_FILE.with_suffix(".jsonl.tmp")
        tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
        os.replace(tmp, EVENT_FILE)
    except (FileNotFoundError, OSError):
        return


def emit(event_type: str, **payload) -> None:
    """Append one UI-safe event. Failures never stop the trading engine."""
    event = {
        "type": event_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    try:
        EVENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, separators=(",", ":"), ensure_ascii=True)
        with _LOCK:
            with EVENT_FILE.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
            _trim_if_needed()
    except Exception as exc:
        print("[hq event recovered]", repr(exc))


def activity(agent: str, text: str, move: bool = True, **extra) -> None:
    emit("activity", agent=agent, text=text, move=move, **extra)


def status(**agents: str) -> None:
    emit("status", status=agents)


def market(symbol: str, value, **extra) -> None:
    emit("market", symbol=symbol, value=str(value), **extra)


def snapshot(symbol: str, features: dict, votes: dict, decision: str | None = None, **extra) -> None:
    """Publish the actual evidence used for a market decision."""
    safe_features = {
        k: round(float(v), 6) if isinstance(v, (int, float)) else str(v)
        for k, v in features.items()
        if k in {
            "price", "r3", "r5", "r10", "r20", "reversion", "trend_gap",
            "vol", "volume_ratio", "range_ratio", "rsi", "breakout", "breakdown",
        }
    }
    safe_votes = {str(k): round(float(v), 6) for k, v in votes.items()}
    emit(
        "snapshot",
        symbol=symbol,
        features=safe_features,
        votes=safe_votes,
        decision=decision,
        **extra,
    )


def heartbeat(text: str = "Engine alive") -> None:
    emit("heartbeat", text=text);
