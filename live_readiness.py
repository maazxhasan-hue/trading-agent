"""Safe live-readiness audit.

This module NEVER enables live trading and NEVER places orders. It only reports
configuration and architectural prerequisites so external blockers are explicit.
"""
from __future__ import annotations

import os


def audit() -> dict:
    provider = os.getenv("NSE_MARKET_DATA_PROVIDER", "yahoo").lower()
    live = os.getenv("LIVE_TRADING", "false").lower() == "true"
    armed = os.getenv("LIVE_TRADING_ARM") == "I_UNDERSTAND_LIVE_TRADING"
    cloud = os.getenv("CLOUD_RUNTIME", "false").lower() == "true"
    approved = os.getenv("LIVE_RUNTIME_APPROVED", "false").lower() == "true"
    api_configured = bool(os.getenv("KITE_API_KEY") and os.getenv("KITE_ACCESS_TOKEN"))

    checks = {
        "paper_mode_default": not live,
        "authorized_market_data_provider": provider == "zerodha",
        "live_runtime_gate": cloud and approved,
        "live_arm_gate": armed,
        "zerodha_credentials_configured": api_configured,
        "static_ip_configured": bool(os.getenv("ZERODHA_STATIC_IP")),
        "external_live_data_entitlement": provider == "zerodha",
        "final_live_approval": False,
    }

    blockers = []
    if provider != "zerodha":
        blockers.append("Authorized Zerodha market-data provider is not configured.")
    if not cloud or not approved:
        blockers.append("Approved cloud runtime is not configured.")
    if not armed:
        blockers.append("Explicit live-trading arm is not enabled.")
    if not api_configured:
        blockers.append("Zerodha credentials are not configured in the runtime.")
    if not checks["static_ip_configured"]:
        blockers.append("Required static IP is not configured.")
    blockers.append("Paper-performance validation must pass before any live approval.")
    blockers.append("Broker order/fill reconciliation must be verified before any live approval.")

    return {
        "live_trading_enabled": live,
        "provider": provider,
        "checks": checks,
        "ready_for_live": False,
        "blockers": blockers,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(audit(), indent=2, sort_keys=True))
