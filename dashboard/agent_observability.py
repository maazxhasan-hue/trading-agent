"""Read-only agent observability API helpers for Trading City HQ.

Configured roles are read from config/agent-roster.yaml. Runtime states and
research history are derived only from actual JSONL engine events.
"""
from __future__ import annotations
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / "config" / "agent-roster.yaml"
EVENT_FILE = Path(__import__("os").environ.get("HQ_EVENT_FILE", str(ROOT / "data" / "hq_events.jsonl")))

ROLE_DETAILS = {
    "ceo": ("Decision coordination", "Collects specialist assessments, records the decision and dissent. Cannot override risk controls."),
    "broad_market_scan": ("Market discovery", "Builds a universe snapshot from markets actually returned by configured providers."),
    "source_integrity_and_freshness": ("Evidence quality", "Checks provenance, freshness, duplicates, missing values and conflicting sources."),
    "market_regime_detection": ("Regime analysis", "Classifies market conditions and records uncertainty and invalidation conditions."),
    "fair_value": ("Fair value estimation", "Estimates value, uncertainty and potential edge after costs."),
    "liquidity_and_slippage": ("Liquidity analysis", "Evaluates spread, depth, market impact and slippage estimates."),
    "macro_calendar_and_event_risk": ("Macro and event research", "Tracks scheduled events and venue/session risks when data is available."),
    "adversarial_review": ("Adversarial review", "Searches for failure modes, counter-theses, leakage, liquidity traps and unsupported assumptions."),
    "risk_manager": ("Independent risk control", "Applies risk limits and can veto a trade; cannot be overruled by the CEO."),
    "portfolio_manager": ("Portfolio and capital", "Checks affordability, exposure, correlation and portfolio constraints."),
    "execution": ("Order execution and reconciliation", "Reports execution adapter state and broker-reported order reconciliation."),
    "execution_quality_monitor": ("Execution quality", "Compares actual fills and costs against estimates."),
    "post_trade_analysis": ("Post-trade learning", "Attributes measured outcomes and creates follow-up validation tasks."),
    "lifecycle_manager": ("Agent lifecycle", "Tracks health and qualification; replacement candidates must pass validation."),
    "operating_budget": ("Treasury", "Tracks separately capped operating budget; must not silently spend trading capital."),
    "audit": ("Audit trail", "Records decision lineage and policy-compliance events."),
    "independent_model_validation": ("Independent validation", "Evaluates calibration, walk-forward results and candidate promotion evidence."),
}
STRATEGY_DETAILS = {
    "momentum": ("Momentum strategy", "Evaluates trend and continuation setups."),
    "mean_reversion": ("Mean reversion strategy", "Evaluates reversion setups and their invalidation conditions."),
    "event_driven": ("Event-driven strategy", "Evaluates setups tied to verified events and event timing."),
    "crypto_specialist": ("Crypto specialist", "Only operates where an approved venue and authorized data connector are configured."),
    "x_social_research": ("X/social research", "Collects authorized social evidence, tracks source provenance and cross-checks claims."),
    "cross_market_arbitrage": ("Cross-market relationships", "Evaluates related-market pricing differences after costs and execution constraints."),
    "volatility_regime": ("Volatility regime", "Evaluates volatility state and strategy suitability."),
    "order_book_imbalance": ("Order-book imbalance", "Evaluates verified order-book imbalance where permitted depth data exists."),
    "trend_breakout": ("Trend breakout", "Evaluates breakout setups with confirmation and invalidation levels."),
    "market_microstructure": ("Market microstructure", "Studies spreads, order flow, liquidity and execution conditions."),
}
DEBATE_DETAILS = {
    "bull": ("Bull thesis", "Builds the strongest evidence-backed case for a candidate."),
    "bear": ("Bear thesis", "Builds the strongest evidence-backed case against a candidate."),
    "quant": ("Quant verifier", "Checks signal calculations, uncertainty, costs and comparability."),
    "news_social": ("News and social evidence", "Cross-checks material claims and separates reports from rumors."),
    "skeptic": ("Skeptic", "Challenges both sides and records unresolved objections."),
    "independent_validator": ("Independent validator", "Checks out-of-sample performance and model calibration."),
}

def _parse_roster():
    agents = []
    try:
        lines = ROSTER.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    section = None
    for line in lines:
        if line and not line.startswith(" ") and line.endswith(":"):
            section = line[:-1]
            continue
        if section == "required_agents":
            match = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if match:
                agent_id = match.group(1)
                role_match = None
                # role is on the next indented line; resolve in a second pass.
                for candidate in lines[lines.index(line)+1:]:
                    if candidate.startswith("  ") and not candidate.startswith("    "):
                        break
                    rm = re.match(r"^    role:\s*([A-Za-z0-9_-]+)", candidate)
                    if rm:
                        role_match = rm.group(1); break
                title, description = ROLE_DETAILS.get(role_match, (role_match or agent_id, "Configured specialist role."))
                agents.append({"id": agent_id, "role": role_match or agent_id, "group": "required", "title": title, "mission": description, "required": True})
        elif section in {"strategy_agents", "debate_agents"}:
            match = re.match(r"^  - ([A-Za-z0-9_-]+)\s*$", line)
            if match:
                agent_id = match.group(1)
                details = STRATEGY_DETAILS if section == "strategy_agents" else DEBATE_DETAILS
                title, description = details.get(agent_id, (agent_id.replace("_", " ").title(), "Configured strategy/debate specialist."))
                agents.append({"id": agent_id, "role": "strategy" if section == "strategy_agents" else "debate", "group": section, "title": title, "mission": description, "required": section == "debate_agents"})
    # Stable unique IDs, retaining the first canonical entry.
    unique = {}
    for agent in agents:
        unique.setdefault(agent["id"], agent)
    return list(unique.values())

def _events():
    try:
        lines = EVENT_FILE.read_text(encoding="utf-8").splitlines()[-3000:]
    except OSError:
        return []
    result = []
    for line in lines:
        try:
            item = json.loads(line)
            if isinstance(item, dict) and item.get("type"):
                result.append(item)
        except (json.JSONDecodeError, TypeError):
            continue
    return result

def agent_snapshot(agent_id=None):
    events = _events()
    definitions = _parse_roster()
    latest_status, latest_activity, analyses, related = {}, {}, [], []
    for item in events:
        stamp = item.get("ts")
        typ = item.get("type")
        if typ == "status" and isinstance(item.get("status"), dict):
            for key, value in item["status"].items():
                latest_status[str(key)] = {"status": str(value).upper(), "ts": stamp}
        agent = str(item.get("agent") or "")
        if typ == "activity" and agent:
            latest_activity[agent] = item
        if typ == "agent_analysis":
            analyses.append(item)
        if agent:
            related.append(item)
    now = time.time()
    for item in definitions:
        aid = item["id"]
        aliases = {aid, aid.replace("_", " "), aid.replace("_", "-")}
        status_event = next((latest_status[a] for a in aliases if a in latest_status), None)
        activity_event = next((latest_activity[a] for a in aliases if a in latest_activity), None)
        if activity_event:
            item["status"] = "ACTIVE" if now - _parse_time(activity_event.get("ts")) < 120 else "STALE"
            item["last_seen"] = activity_event.get("ts")
            item["last_activity"] = activity_event.get("text")
        elif status_event:
            item["status"] = status_event["status"]
            item["last_seen"] = status_event["ts"]
            # A historical ACTIVE/WORKING status is not proof of a live worker.
            status_age = now - _parse_time(status_event["ts"])
            if item["status"] in {"ACTIVE", "WORKING", "RUNNING", "MONITORING", "CONNECTED", "HEALTHY"} and status_age >= 120:
                item["status"] = "STALE"
            item["last_activity"] = None
        else:
            item["status"] = "NOT RUN / NO DATA"
            item["last_seen"] = None
            item["last_activity"] = None
        item["last_seen_age_seconds"] = round(max(0, now - _parse_time(item["last_seen"])), 1) if item["last_seen"] else None
        item["research"] = [x for x in analyses if str(x.get("agent") or "") in aliases][-30:]
        item["events"] = [x for x in related if str(x.get("agent") or "") in aliases][-50:]
        item["recent_evidence_count"] = sum(len(x.get("evidence") or []) for x in item["research"])
        item["order_execution_access"] = False if item["group"] != "required" or item["role"] != "execution" else "adapter-gated"
    if agent_id:
        return next((x for x in definitions if x["id"] == agent_id), None)
    return {"generated_at": time.time(), "source": "configured roster + actual HQ event journal", "agents": definitions}

def _parse_time(value):
    if not value:
        return 0.0
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OverflowError):
        try: return float(value)
        except (ValueError, TypeError): return 0.0
