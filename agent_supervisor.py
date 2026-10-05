"""Cloud supervisor for isolated trading agents."""
import os
import time
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

    def validation(self):
        """Expose real validation progress without authorizing trades."""
        try:
            from agent_learning import AgentLearningStore
            store = AgentLearningStore()
            ids = [
                "momentum-v1", "mean_reversion-v1", "event_driven-v1",
                "crypto_specialist-v1", "x_social_research-v1",
                "cross_market_arbitrage-v1",
            ]
            qualified, details = store.qualified_agents(ids)
            return {
                "status": "qualified" if len(qualified) >= 3 else "collecting",
                "qualified_count": len(qualified),
                "required": 3,
                "qualified_agents": qualified,
                "resolved_forecasts": len(store.data.get("history", [])),
                "pending_forecasts": len(store.data.get("pending", [])),
                "observations": store.observation_count(),
                "agents": details,
                "live_trading_authorized": False,
            }
        except Exception as exc:
            return {
                "status": "unavailable",
                "error": repr(exc),
                "live_trading_authorized": False,
            }

    def run_health_server(self):
        port = int(os.getenv("PORT", "8080"))

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in ("/", "/health", "/healthz"):
                    payload = {"status": "ok", "service": "trading-company"}
                elif self.path == "/validation":
                    payload = self.validation()
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def run(self):
        self.run_health_server()
        from agent import TradingCompany
        company = TradingCompany()
        interval = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))
        next_run = time.monotonic()
        while True:
            self.write_health()
            try:
                company.cycle()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print("[supervisor] recovered:", repr(exc))
            next_run += interval
            time.sleep(max(0.0, next_run - time.monotonic()))

if __name__ == "__main__":
    AgentSupervisor().run()
