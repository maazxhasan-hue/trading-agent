"""Cloud supervisor for isolated trading agents.

Runs independently of the user's laptop. It provisions one runtime per agent,
checks runtime health, and invokes the trading engine on its configured cadence.
"""
import os, time, json
from datetime import datetime, timezone
from agent_runtime import AgentRuntimeManager

AGENTS = [
    "orchestrator","market-scanner","fair-value","momentum","mean-reversion",
    "event-driven","crypto-specialist","x-social-research",
    "cross-market-arbitrage","bull","bear","quant","news-social",
    "red-team","risk","portfolio","execution","post-trade","agent-health",
    "treasury","audit",
]

class AgentSupervisor:
    def __init__(self):
        self.runtime = AgentRuntimeManager(
            os.getenv("AGENT_WORKSPACE_ROOT", "agent_workspaces")
        )
        self.runtimes = {agent: self.runtime.provision(agent) for agent in AGENTS}

    def health(self):
        return {
            agent: {
                "workspace": str(rt.workspace),
                "browser_profile": str(rt.browser_profile),
                "browser_enabled": rt.policy.browser_enabled,
                "terminal_enabled": rt.policy.terminal_enabled,
            }
            for agent, rt in self.runtimes.items()
        }

    def write_health(self):
        path = os.getenv("AGENT_HEALTH_FILE", "logs/agent_runtime_health.json")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "time": datetime.now(timezone.utc).isoformat(),
                "agents": self.health(),
            }, f, indent=2)

    def run(self):
        from agent import TradingCompany
        company = TradingCompany()
        interval = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))
        while True:
            self.write_health()
            try:
                company.cycle()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print("[supervisor] recovered:", repr(exc))
            time.sleep(interval)

if __name__ == "__main__":
    AgentSupervisor().run()
