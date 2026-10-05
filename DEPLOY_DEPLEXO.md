# Deplexo free deployment

This repository uses a lightweight Docker image for Deplexo's constrained free runtime.

## Deploy

1. Create a Deplexo account with email or GitHub.
2. Connect GitHub repository maazxhasan-hue/trading-agent.
3. Deploy the app.
4. Deplexo reads `deplexo.yaml`, uses `Dockerfile.deplexo`, and exposes port 8080.
5. Add environment variables in the Deplexo dashboard:
   `LIVE_TRADING=false`
   `LIVE_TRADING_ARM=`
   `SCAN_INTERVAL_SECONDS=300`
   `RESEARCH_MARKETS_PER_CYCLE=25`
   `MAX_RESEARCH_AGE_SECONDS=900`
   `REQUIRE_EVENT_CALENDAR=false`
   `REQUIRE_X_SOCIAL=false`
   `AGENT_WORKSPACE_ROOT=/data/agent_workspaces`
   `AGENT_HEALTH_FILE=/data/logs/agent_runtime_health.json`
   `AGENT_LIFECYCLE_FILE=/data/agent_lifecycle.json`
   `AGENT_CALIBRATION_FILE=/data/agent_calibration.json`
   `TRADING_LOG_FILE=/data/paper_trades.csv`
   `TRADING_KILL_SWITCH=false`
   `MAX_EXECUTION_SLIPPAGE=0.02`
   `MIN_BOOK_DEPTH_MULTIPLE=2.0`
6. Attach the persistent data volume at `/data` if available.
7. Confirm the health URL returns HTTP 200.

## Runtime scope

The free image intentionally omits Playwright/Chromium. The isolated browser/terminal runtime remains part of the full architecture and is enabled by the main Dockerfile, but a constrained free deployment should be treated as a paper-mode research/orchestration environment.

## Safety

Keep live execution disabled on the free deployment. Do not put private keys, wallet seeds, API secrets, or bearer tokens into GitHub. Use protected platform secrets if optional authenticated research is enabled.

No system in this repository guarantees profit. Paper results are simulations and must not be treated as proof of future performance.
