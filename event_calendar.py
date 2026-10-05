"""Optional event/calendar evidence connector for research.

A public JSON or ICS endpoint may be supplied through EVENT_CALENDAR_URL.
No events are fabricated when the connector is unavailable.
"""
from dataclasses import dataclass
import os
import requests

@dataclass
class EventEvidence:
    title: str
    start: str
    relevance: float
    source: str = "event_calendar"

def _parse_json(payload):
    rows = payload.get("events", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    out = []
    for row in rows[:50]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or row.get("name") or "").strip()
        start = str(row.get("start") or row.get("start_time") or "").strip()
        if title:
            out.append(EventEvidence(title, start, 0.7))
    return out

def _parse_ics(text):
    out, current = [], {}
    for line in text.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT":
            title = current.get("SUMMARY", "").strip()
            start = current.get("DTSTART", "").strip()
            if title:
                out.append(EventEvidence(title, start, 0.7))
            current = {}
        elif ":" in line:
            key, value = line.split(":", 1)
            current[key.split(";", 1)[0]] = value
    return out[:50]

def fetch_events(question, timeout=5):
    url = os.getenv("EVENT_CALENDAR_URL", "").strip()
    if not url:
        return [], "unavailable_no_calendar_url"
    try:
        r = requests.get(
            url, params={"q": question[:180]}, timeout=timeout,
            headers={"User-Agent": "TradingCompanyEvents/1.0"},
        )
        r.raise_for_status()
        if "json" in r.headers.get("content-type", "").lower() or r.text.lstrip().startswith(("{", "[")):
            events = _parse_json(r.json())
        else:
            events = _parse_ics(r.text)
        return events, "ok" if events else "ok_no_events"
    except Exception:
        return [], "unavailable_request_error"
