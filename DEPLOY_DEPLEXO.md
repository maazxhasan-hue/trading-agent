# Deplexo free deployment

Deplexo currently offers a $0 tier with one always-on app and no credit card. Its free tier is constrained to 128 MB RAM, 0.25 CPU and 250 MB disk, so this repository uses a lightweight image on Deplexo.

## Deploy

1. Create a Deplexo account with email or GitHub.
2. Connect GitHub repository maazxhasan-hue/trading-agent.
3. Deploy the app.
4. Deplexo reads deplexo.yaml, uses Dockerfile.deplexo, and exposes port 8080.
5. Add environment variables in the Deplexo dashboard:
   LIVE_TRADING=false
   LIVE_TRADING_ARM=
   SCAN_INTERVAL_SECONDS=300
   AGENT_WORKSPACE_ROOT=/data/agent_workspaces
   AGENT_HEALTH_FILE=/data/logs/agent_runtime_health.json
6. Attach the persistent data volume at /data if available.
7. Confirm the health URL returns HTTP 200.

## Free-tier limitation

The free tier has only 128 MB RAM, so it cannot realistically keep Chromium/browser agents running. Dockerfile.deplexo intentionally omits Playwright/Chromium. This is a hosting limitation, not a removal from the overall trading-company architecture.

Do not enable live trading on this constrained deployment. Use it for paper-mode orchestration, scanning and validation until it is moved to a larger runtime.

Never put private keys or API secrets into GitHub. If live trading is eventually enabled on a larger verified runtime, store credentials only in protected platform secrets.
