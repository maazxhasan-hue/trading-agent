#!/usr/bin/env python3
"""Read-only Angel One auth diagnostics. This script never calls SmartAPI."""
from __future__ import annotations
import json
import os
import subprocess
import shlex
import urllib.request
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from angelone_auth import read_auth_status

SERVICES = ("trading-agent.service", "mcx-paper.service", "angelone-multi-paper.service")

def _run(command):
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=8, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""

def _safe_error(text):
    low = text.lower()
    if "exceeding access rate" in low or ("403" in low and "rate" in low):
        return "login endpoint: HTTP 403 access-rate denial"
    if "login" in low and ("failed" in low or "error" in low):
        return "login endpoint: authentication failure"
    if "timeout" in low or "connection" in low:
        return "login endpoint: network failure"
    return "Angel One authentication error (details suppressed)"

def _safe_environment(system_reader):
    """Load only non-secret diagnostic settings from the service env file."""
    env = dict(os.environ)
    allowed = {"ANGELONE_CLIENT_PUBLIC_IP", "ANGELONE_AUTH_STATE_PATH", "ANGELONE_AUTH_LOG"}
    if all(env.get(key) for key in allowed):
        return env
    files = system_reader(["systemctl", "show", "trading-agent.service", "-p", "EnvironmentFiles", "--value"])
    for item in files.splitlines():
        candidate = item.strip().split(" (", 1)[0].lstrip("-")
        if not candidate.startswith("/"):
            continue
        try:
            lines = Path(candidate).read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, raw = line.partition("=")
            key = key.strip()
            if not sep or key not in allowed or env.get(key):
                continue
            try:
                parts = shlex.split(raw, comments=False, posix=True)
                env[key] = " ".join(parts) if parts else ""
            except ValueError:
                continue
    if env.get("ANGELONE_AUTH_STATE_PATH") and not os.environ.get("ANGELONE_AUTH_STATE_PATH"):
        os.environ["ANGELONE_AUTH_STATE_PATH"] = env["ANGELONE_AUTH_STATE_PATH"]
    return env

def diagnose(system_reader=_run, public_ip_reader=None, state_reader=read_auth_status, env=None):
    env = _safe_environment(system_reader) if env is None else env
    services = {}
    for service in SERVICES:
        output = system_reader(["systemctl", "is-active", service]).strip()
        services[service] = output if output in {"active", "inactive", "failed", "activating", "deactivating"} else "unknown"
    process_output = system_reader(["ps", "-eo", "args="])
    names = ("agent_supervisor.py", "mcx_agent.py", "angelone_multi_agent.py")
    process_counts = {name: sum(name in line for line in process_output.splitlines()) for name in names}
    matcher = lambda line: any(term in line.lower() for term in ("trading-agent", "mcx-paper", "angelone", "agent-supervisor"))
    services_output = system_reader(["systemctl", "list-units", "--type=service", "--all", "--no-legend"])
    matching_services = []
    for line in services_output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and matcher(fields[0]):
            matching_services.append({"unit": fields[0], "state": fields[2]})
    timers_output = system_reader(["systemctl", "list-timers", "--all", "--no-legend"])
    matching_timers = []
    for line in timers_output.splitlines():
        fields = line.split()
        if len(fields) >= 6 and matcher(fields[4]):
            matching_timers.append(fields[4])
    cron_output = system_reader(["crontab", "-l"])
    matching_cron_entries = sum(1 for line in cron_output.splitlines() if line.strip() and not line.lstrip().startswith("#") and matcher(line))
    configured_ip = env.get("ANGELONE_CLIENT_PUBLIC_IP") or None
    if public_ip_reader:
        current_ip = public_ip_reader()
    else:
        try:
            with urllib.request.urlopen("https://api.ipify.org", timeout=4) as response:
                current_ip = response.read(64).decode("ascii").strip()
        except Exception:
            current_ip = None
    state = state_reader()
    log_path = Path(env.get("ANGELONE_AUTH_LOG", "/var/log/trading-agent/angelone.log"))
    recent = []
    log_lines = []
    try:
        log_lines.extend(log_path.read_text(errors="replace").splitlines()[-300:])
    except OSError:
        pass
    for service in SERVICES:
        log_lines.extend(system_reader(["journalctl", "-u", service, "--since", "24 hours ago", "--no-pager", "-n", "100"]).splitlines())
    for line in log_lines:
        if "angel" in line.lower() and ("login" in line.lower() or "rate" in line.lower() or "auth" in line.lower()):
            recent.append(_safe_error(line))
    return {"services": services, "matching_systemd_services": matching_services,
            "matching_systemd_timers": matching_timers, "matching_cron_entries": matching_cron_entries,
            "process_counts": process_counts,
            "configured_public_ip": configured_ip, "current_public_ip": current_ip,
            "public_ip_matches": (configured_ip == current_ip) if configured_ip and current_ip else None,
            "auth": state, "recent_auth_errors": list(dict.fromkeys(recent))[-10:]}

def main():
    print(json.dumps(diagnose(), indent=2, sort_keys=True))

if __name__ == "__main__":
    main()
