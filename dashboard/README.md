# Trading Agent HQ — Live Command Center

The HQ is connected to the real trading-engine event stream.

## What is real

The engine publishes events when it actually:
- scans the market
- computes feature evidence
- receives each strategy vote
- runs the actual specialist debate and records challenges
- runs Red Team and Risk/Chief decision flow
- opens/closes a paper position
- updates learning

The characters are driven by those events. The browser does **not** invent a
production work loop.

## Event stream

The page connects to `/events` using Server-Sent Events (SSE).

Supported messages include:
- `activity`: moves an agent and adds a live activity entry
- `market`: updates a market display
- `status`: updates agent state
- `snapshot`: carries actual feature values and votes used for a decision
- `heartbeat`: proves the engine is alive

## Run locally

From the repository root:

```bash
python dashboard/hq_server.py
```

Then open `http://127.0.0.1:8787`.

The engine writes events to `data/hq_events.jsonl`. Set `HQ_EVENT_FILE`
to override the path.

## Azure systemd

Copy `deploy/trading-agent-hq.service` to
`/etc/systemd/system/trading-agent-hq.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now trading-agent-hq
curl http://127.0.0.1:8787/health
```

Keep the listener on localhost and expose it only through a private
authentication layer such as Cloudflare Access/Tunnel. Never put broker
credentials in the frontend.

This dashboard is visualization only; it does not place broker orders.
