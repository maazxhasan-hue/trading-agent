# Adaptive Agent Lifecycle

The engine uses a controlled evolutionary loop:

1. Every paper trade records which agents supported the thesis.
2. When the trade settles, a loss triggers diagnosis.
3. Supporting agents are quarantined immediately; they cannot vote on the next trade.
4. The lifecycle manager creates a mutated replacement using the diagnosed failure as the mutation reason.
5. The replacement is validated against a deterministic holdout before activation.
6. If validation is below the configured floor, no replacement is activated.
7. There is no revenge trade, automatic doubling, or averaging down.

"Kill" means logical retirement/quarantine of the strategy instance. It does not terminate the whole trading engine.
