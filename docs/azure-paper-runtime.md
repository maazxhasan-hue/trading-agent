# Paper-first Azure VM runtime

This is an operator-run deployment template, not a deployment action. Nothing in
this PR starts the Azure VM, installs the service, or enables live orders.

## Before installation

1. Confirm the VM is running and the expected repository commit is deployed.
2. Create a dedicated `trading-agent` OS user and install project dependencies in
   `/opt/trading-agent/.venv`.
3. Ensure `/opt/trading-agent/data` is writable by that user and backed up.
4. Keep `LIVE_TRADING=false` and `ANGELONE_READONLY=true`. Do not place secret
   values in this service file, logs, screenshots, or Git.
5. Run the test suite and inspect the actual MCX futures contract/lot-size checks.

## Install manually after explicit operator approval

Copy `deploy/trading-agent.service.example` to
`/etc/systemd/system/trading-agent.service`, create the environment file with
restricted permissions, then run `systemctl daemon-reload`. Only an operator
should run `systemctl enable --now trading-agent` after reviewing the deployment.
This repository change does not execute those commands.

## Monitoring

- `systemctl status trading-agent`
- `journalctl -u trading-agent -f`
- Inspect `data/mcx_gen_evolution.json`, `data/mcx_tournament.json`,
  `data/mcx_gen_portfolios.json`, and HQ event stream.
- A service restart preserves the tournament deadline and generation lineage.
  Verify that the files are on persistent disk.

## Honest outcome semantics

The 3-hour deadline can return a qualified paper champion or
`NO_QUALIFIED_CHAMPION`. A paper champion continues in paper mode; if it is
eliminated by a loss, the controller starts a fresh bounded evolution session.
The controller never triggers Angel One validation or enables live orders.
A ₹1,000/hour target from ₹100 is a scoring goal, not a promise of returns.
