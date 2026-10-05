# Oracle Cloud Always Free deployment

This repository is prepared for an always-on Oracle Cloud Always Free VM. The cloud machine runs the trading supervisor independently of the user's laptop.

## Recommended shape

- Oracle Cloud Always Free Ampere A1 ARM64 VM
- Docker + Docker Compose
- Persistent agent workspaces and runtime logs
- Isolated browser profiles/workspaces per agent
- Browser processes started as needed instead of keeping 21 browsers alive
- 5-minute supervisor cycle
- Paper trading by default
- Live trading explicitly locked

Always Free resources and regional capacity can change, so verify the current limits and ARM64 image availability in the Oracle console.

## Deploy

1. Create an Oracle Always Free ARM64 VM and add your own SSH public key.
2. SSH into the VM.
3. Run:

    curl -fsSL https://raw.githubusercontent.com/maazxhasan-hue/trading-agent/main/deploy/install.sh -o /tmp/install.sh
    bash /tmp/install.sh

4. Check:

    cd /opt/trading-agent
    docker compose ps
    docker compose logs --tail=100 trading-company

## Secrets

The VM creates a protected environment file. Keep:

    LIVE_TRADING=false
    LIVE_TRADING_ARM=

Never commit wallet private keys, API credentials, browser sessions, or the environment file to GitHub.

Live trading requires an independently verified account and credentials and remains disabled until explicitly armed.

## Updating

    cd /opt/trading-agent
    git pull --ff-only
    docker compose build
    docker compose up -d

The laptop can be powered off after the cloud VM is running.

## Security

Only expose SSH and ports that the application actually needs. Never expose Docker's API socket or port publicly.
