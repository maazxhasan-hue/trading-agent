# Trading Engine v2

The repository now contains a paper-trading research engine with:

- public market discovery and historical price retrieval
- fair-value ensemble
- momentum and mean-reversion signals
- 8% edge and 80% confidence gates
- fractional Kelly capped at 6%
- portfolio exposure and daily-loss limits
- confidence calibration and Brier-score tracking
- authorized evidence/event scoring
- walk-forward out-of-sample evaluation
- persistent post-trade agent-health diagnostics
- automated Python regression tests

Run:
python -m unittest discover -s tests -v
python agent.py

Backtest:
python walk_forward.py history.csv

Default execution remains paper-only. No private credentials belong in GitHub. Past performance is not a guarantee of future returns.
