"""Runtime safety gates for unattended live trading.

Live execution is allowed only from an explicitly approved cloud runtime.
This prevents a laptop/local checkout from accidentally placing real orders.
"""

import os


class LiveRuntimeNotApproved(Exception):
    """Raised when live trading is requested outside an approved runtime."""


def cloud_runtime_enabled() -> bool:
    return os.getenv("CLOUD_RUNTIME", "false").lower() == "true"


def live_runtime_approved() -> bool:
    return os.getenv("LIVE_RUNTIME_APPROVED", "false").lower() == "true"


def require_live_runtime() -> None:
    if not cloud_runtime_enabled():
        raise LiveRuntimeNotApproved(
            "Live trading is cloud-only. Set CLOUD_RUNTIME=true on the "
            "unattended cloud deployment; local/laptop live trading is blocked."
        )
    if not live_runtime_approved():
        raise LiveRuntimeNotApproved(
            "Cloud runtime is not approved for live trading. Set "
            "LIVE_RUNTIME_APPROVED=true only after production readiness checks."
        )
