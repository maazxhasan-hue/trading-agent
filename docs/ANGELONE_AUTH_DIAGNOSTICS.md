# Angel One authentication diagnostics

Run the read-only diagnostic as root from the deployed repository directory so it can read the service's protected environment file and auth-state file:

    cd /opt/trading-agent
    sudo -n .venv/bin/python scripts/diagnose_angelone_auth.py

The script reads only the non-secret `ANGELONE_CLIENT_PUBLIC_IP`, `ANGELONE_AUTH_STATE_PATH`, and `ANGELONE_AUTH_LOG` values from the systemd EnvironmentFile. It never loads or prints API keys, PINs, TOTP secrets, or tokens. It reads systemd service/timer inventory, matching cron entry counts, process names/counts, the configured and observed public egress IP, the local authentication state file, and a limited set of local log/journal lines. It reports service and timer names/counts only; cron command text and raw logs are never printed. It never sends a request to Angel One. It may query https://api.ipify.org only to identify current egress IP. Inspect output before sharing it because public IPs are operational information. If the configured IP or state is inaccessible, the script reports it as unknown rather than treating it as a mismatch.

The auth state file defaults to /var/lib/trading-agent/angelone-auth.json; override with ANGELONE_AUTH_STATE_PATH. Before a future authorized rollout, ensure the parent directory is writable only by the service account (for example, inspect `systemctl show -p User --value trading-agent.service`, then prepare the directory for that account). The diagnostic command itself does not create state files or change system configuration. It contains session tokens and must remain owner-only (0600) with a parent directory accessible only to the service account. Cooldown is a local circuit breaker, not Angel One's published block duration. A RATE_LIMITED report means the process must not initiate another login before the recorded cooldown ends.

Do not repeatedly test the live login endpoint while blocked. Ask Angel One support to confirm the account/IP restriction and its clearance. Once support confirms clearance and the local cooldown has expired, obtain explicit operator approval before one controlled authentication test. Keep LIVE_TRADING=false and ANGELONE_READONLY=true; never place a test order.
