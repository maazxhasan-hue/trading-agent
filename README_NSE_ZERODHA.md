# NSE + Zerodha production trading path

The repository now supports an Indian NSE cash-equity backend through Zerodha Kite Connect while preserving the existing Polymarket engine.

## Architecture

`Zerodha market data -> NSE feature engine -> independent strategy forecasts -> persistent learning -> 30-sample + walk-forward qualification -> portfolio/risk gates -> paper limit orders -> optional live Zerodha limit orders`

The NSE engine is in `nse_agent.py`, market access is in `nse_market_data.py`, and authenticated execution is in `zerodha_adapter.py`.

## Important runtime facts

- Zerodha has no API sandbox. Keep `LIVE_TRADING=false` while the qualification dataset is being collected.
- Kite Connect Personal is free for order/portfolio APIs but does not include real-time or historical data. The paid Connect plan provides live WebSocket and historical candle data.
- API order placement requires a whitelisted static IP under the current Zerodha rules.
- Live credentials belong in deployment secrets, never GitHub.
- Access tokens are session credentials and must be refreshed according to Zerodha's login flow; `zerodha_auth.py` handles the request-token exchange.
- The engine uses limit orders by default and intraday MIS by default. It does not claim guaranteed returns.

## Setup

1. Create a Zerodha account and a Kite Connect app.
2. Configure the app redirect URL.
3. Obtain the API key/secret.
4. Run `zerodha_auth.py` after login to obtain the access token.
5. Put `KITE_API_KEY`, `KITE_API_SECRET`, and `KITE_ACCESS_TOKEN` into the deployment secret store.
6. Set `TRADING_BACKEND=zerodha_nse`.
7. Keep `LIVE_TRADING=false`.
8. Start the service and allow the learning store to collect real NSE observations.
9. Do not lower `LEARNING_MIN_SAMPLES=30` or the walk-forward gates to force a trade.

Zerodha documents the developer signup/app creation flow and API credentials here.

## Live activation

Only after the model qualification and paper validation gates are genuinely satisfied should the live execution path be considered. Live mode additionally requires:

`LIVE_TRADING=true`
`LIVE_TRADING_ARM=I_UNDERSTAND_LIVE_TRADING`
`CLOUD_RUNTIME=true`
`LIVE_RUNTIME_APPROVED=true`
`KITE_API_KEY`
`KITE_ACCESS_TOKEN`
and a Zerodha-whitelisted static IP.

The code deliberately refuses live execution when any of these conditions are missing.
