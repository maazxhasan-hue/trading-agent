"""Safe live-readiness audit for the configured Angel One MCX runtime.

This module NEVER enables live trading and NEVER places orders. It reports
configuration prerequisites and deliberately leaves final approval to the
separate operational and performance gates.
"""
from __future__ import annotations

import os


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "true"


def audit() -> dict:
    provider = os.getenv("MCX_MARKET_DATA_PROVIDER", "yahoo").strip().lower()
    backend = os.getenv("TRADING_BACKEND", "angelone_mcx").strip().lower()
    live = _enabled("LIVE_TRADING")
    armed = os.getenv("LIVE_TRADING_ARM") == "I_UNDERSTAND_LIVE_TRADING"
    cloud = _enabled("CLOUD_RUNTIME")
    approved = _enabled("LIVE_RUNTIME_APPROVED")
    api_configured = all(os.getenv(name, "").strip() for name in (
        "ANGELONE_API_KEY",
        "ANGELONE_CLIENT_CODE",
        "ANGELONE_PIN",
        "ANGELONE_TOTP_SECRET",
    ))
    static_ip_configured = bool(os.getenv("ANGELONE_CLIENT_PUBLIC_IP", "").strip())
    provider_authorized = provider == "angelone" and backend == "angelone_mcx"

    checks = {
        "paper_mode_default": not live,
        "authorized_market_data_provider": provider_authorized,
        "live_runtime_gate": cloud and approved,
        "live_arm_gate": armed,
        "angelone_credentials_configured": api_configured,
        "static_ip_configured": static_ip_configured,
        "external_live_data_entitlement": provider_authorized,
        "final_live_approval": False,
    }

    blockers = []
    if not provider_authorized:
        blockers.append("Angel One MCX backend and market-data provider are not both configured.")
    if not cloud or not approved:
        blockers.append("Approved cloud runtime is not configured.")
    if not armed:
        blockers.append("Explicit live-trading arm is not enabled.")
    if not api_configured:
        blockers.append("Angel One credentials are not configured in the runtime.")
    if not static_ip_configured:
        blockers.append("Registered Angel One static public IP is not configured.")
    blockers.append("Paper-performance validation must pass before any live approval.")
    blockers.append("Broker order/fill reconciliation must be verified before any live approval.")
    blockers.append("Instrument quantity, notional budget, available funds, margin, and charges must be verified before every order.")

    return {
        "live_trading_enabled": live,
        "provider": provider,
        "backend": backend,
        "checks": checks,
        "ready_for_live": False,
        "blockers": blockers,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(audit(), indent=2, sort_keys=True))
