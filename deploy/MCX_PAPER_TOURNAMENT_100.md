# Isolated ₹100 MCX paper tournament

This service is deliberately separate from `mcx-paper-planb.service`. It uses separate state, learning, and journal files and runs for at most one hour. It must remain paper-only.

## Important limits

- The default CI feed is Yahoo global-futures proxy data, **not actual MCX exchange prices or tradable MCX contracts**. Use it for software checks only; the Angel One validation stage must use fresh Angel One MCX quotes.
- Fractional units are simulation-only and must never be used for broker orders.
- The tournament objective is to test whether a candidate can reach ₹1,000 net simulated P&L within a 3,600-second window. It is an experiment metric, not a promised or expected return. The continuous CI workflow runs one scan per invocation; it does not by itself prove a one-hour result. The one-hour Azure service is a separate run and must retain its own persisted state and timestamps.
- Promotion is not based on hitting the ₹1,000 target alone. Candidates must also pass out-of-sample validation, net-of-cost drawdown and stability gates, plus independent Angel One paper validation using actual MCX quotes and real contract lot sizes. A failed or unverified gate means no promotion.
- The CI workflow uses Yahoo global-futures proxy data and a ₹100,000 paper book; it cannot certify actual MCX performance or be treated as the final candidate tournament.
- The 6% setting caps paper position notional at 6% of current paper capital; this is stricter than risking 6% of capital at the stop. It does not guarantee a 6% stop-loss outcome.
- The evolutionary lifecycle stores a generic loss lesson and inherited history; it does not automatically make the successor stronger.
- The existing Plan B service and its state file must not be edited or reset.

## Deploy after reviewing/merging this change

On the Azure VM:

```bash
cd /opt/trading-agent
git pull --ff-only origin main
/opt/trading-agent/.venv/bin/python -m py_compile nse_agent.py mcx_agent.py
sudo install -m 0644 deploy/mcx-paper-tournament-100.service.example /etc/systemd/system/mcx-paper-tournament-100.service
sudo systemctl daemon-reload
```

Before starting, verify the current Plan B service remains active and the tournament service is not already running:

```bash
sudo systemctl is-active mcx-paper-planb
sudo systemctl is-active mcx-paper-tournament-100 || true
```

Start the separate tournament only after those checks:

```bash
sudo systemctl start mcx-paper-tournament-100
sudo systemctl status mcx-paper-tournament-100 --no-pager
tail -f /opt/trading-agent/logs/mcx-tournament-100.log
```

The service's `timeout` wrapper ends the process after one hour. Results remain in `data/mcx_tournament_100_state.json`, `data/mcx_tournament_100_learning.json`, and `data/mcx_tournament_100_journal.jsonl`. Inspect results after it stops; do not infer success from the process being active.
