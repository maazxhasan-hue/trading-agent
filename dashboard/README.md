# Trading Agent HQ — Animated Command Center

This is the visual operations UI for the trading-agent system.

- Each specialist has its own animated office/cabin.
- Bull/Bear/Quant/News have a discussion room.
- Red Team, Risk and Chief have dedicated rooms.
- Characters move and animate when events arrive.
- The production event stream is intended to come from the real Azure trading engine.
- The fallback demo keeps the UI alive until the backend event stream is connected.

## Event stream
The page connects to `/events` using Server-Sent Events (SSE). Supported messages:
`{"type":"activity","agent":"momentum","text":"Scanning GOLD","move":true}`
`{"type":"market","symbol":"GOLD","value":"8924.0"}`
`{"type":"status","status":{"momentum":"WORKING","risk":"IDLE"}}`

## Security
No broker credentials belong in the browser. Put the dashboard behind a private authentication layer such as Cloudflare Access before exposing it publicly.

This dashboard is visualization only and does not place orders.