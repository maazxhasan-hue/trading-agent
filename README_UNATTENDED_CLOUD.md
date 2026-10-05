# Unattended Cloud Trading

The trading engine is designed so the **laptop is not the trading host**.

## Runtime model

```
Laptop OFF
   |
   v
Cloud container (24/7, restart-on-failure)
   |
   +--> market scan every 5 minutes
   +--> research / fair value / strategy debate
   +--> red-team / portfolio / execution-risk gates
   +--> live execution gateway (only when explicitly armed)
   +--> order + fill reconciliation
   +--> persistent portfolio state under /data
```

Once a production cloud deployment is running, the user's laptop can be completely powered off. The cloud process does not depend on a browser session, local terminal, or local network connection.

## Live-trading safety

Live execution has **three independent locks**:

1. `LIVE_TRADING=true`
2. `LIVE_TRADING_ARM=I_UNDERSTAND_LIVE_TRADING`
3. `CLOUD_RUNTIME=true` and `LIVE_RUNTIME_APPROVED=true`

The third lock is important: a local laptop/desktop checkout cannot accidentally place real orders even if someone sets the first two variables.

Private keys and API credentials must be stored only in the cloud provider's protected secret/environment-variable store. Never commit them to GitHub.

## Deployment sequence

1. Run paper trading and collect meaningful out-of-sample validation.
2. Move the engine to a persistent cloud runtime with restart-on-failure and persistent `/data`.
3. Configure protected Polymarket credentials in the cloud provider.
4. Keep `LIVE_RUNTIME_APPROVED=false` while validating the cloud runtime.
5. Verify health, feed freshness, agent qualification, risk gates, order reconciliation and portfolio state persistence.
6. Only then set `LIVE_RUNTIME_APPROVED=true`, and separately arm live execution.
7. Keep the laptop offline or powered down; the cloud continues operating independently.

## Important

This does not guarantee profit. Live trading can lose money. Do not bypass authentication, KYC, rate limits or platform security. The engine does not contain a laptop-off workaround; it simply runs in the cloud, which is the correct architecture for unattended operation.
