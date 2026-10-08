"""Cloud supervisor for isolated trading agents."""
import os
import time
import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent_runtime import AgentRuntimeManager
from agent_research_tools import AgentResearchTools

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
        self.research_tools = AgentResearchTools(self.runtime)

    def health(self):
        return {
            agent: {
                "workspace": str(rt.workspace),
                "browser_profile": str(rt.browser_profile),
                **self.runtime.capability_status(rt),
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

    def _learning_path(self, backend):
        configured = os.getenv("AGENT_LEARNING_FILE")
        if configured:
            return configured
        if backend == "mcx":
            return "/data/mcx_agent_learning.json" if os.path.isdir("/data") else "mcx_agent_learning.json"
        if backend == "zerodha_nse":
            return "/data/nse_agent_learning.json" if os.path.isdir("/data") else "nse_agent_learning.json"
        return "/data/agent_learning.json" if os.path.isdir("/data") else "agent_learning.json"

    def validation(self):
        """Expose real validation progress without authorizing trades."""
        try:
            from agent_learning import AgentLearningStore
            backend = os.getenv("TRADING_BACKEND", "mcx").lower()
            store = AgentLearningStore(path=self._learning_path(backend))
            ids = ["momentum-v3", "mean_reversion-v3", "event_driven-v3", "cross_market_arbitrage-v3"]
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
            return {"status": "unavailable", "error": repr(exc), "live_trading_authorized": False}

    def metrics(self):
        try:
            from agent_learning import AgentLearningStore
            backend = os.getenv("TRADING_BACKEND", "mcx").lower()
            store = AgentLearningStore(path=self._learning_path(backend))
            metrics_path = os.getenv("PAPER_METRICS_FILE", "/data/paper_metrics.json" if os.path.isdir("/data") else "paper_metrics.json")
            paper = {}
            if os.path.exists(metrics_path):
                with open(metrics_path, encoding="utf-8") as f:
                    raw = json.load(f)
                    paper = raw if isinstance(raw, dict) else {}
            feed_status = "zerodha_mcx" if backend == "mcx" else ("zerodha_quote" if backend == "zerodha_nse" else "polymarket_gamma")
            return {
                "backend": backend,
                "feed": {"status": feed_status},
                "validation": self.validation(),
                "paper": paper,
                "live_trading_authorized": False,
            }
        except Exception as exc:
            return {"status": "unavailable", "error": repr(exc), "live_trading_authorized": False}

    def dashboard_html(self):
        data = self.metrics()
        validation = data.get("validation", {})
        agents = validation.get("agents", {})
        rows = "".join(
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                a,
                v.get("forecasts", 0),
                "N/A" if v.get("accuracy") is None else "{:.1%}".format(v["accuracy"]),
                "N/A" if v.get("brier") is None else "{:.4f}".format(v["brier"]),
                "YES" if v.get("qualified") else "NO",
            )
            for a, v in sorted(agents.items())
        )
        return """<!doctype html><html><head><meta charset="utf-8">
<title>Trading Company Validation</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:system-ui;margin:2rem;line-height:1.4}table{border-collapse:collapse;width:100%%}th,td{padding:.55rem;border:1px solid #ccc;text-align:left}code{background:#eee;padding:.15rem .3rem}.ok{font-weight:700}</style>
</head><body><h1>Trading Company — Validation</h1>
<p class="ok">Status: {status}</p>
<p>Qualified: <b>{qualified}</b> / <b>{required}</b> &nbsp; | &nbsp; Resolved forecasts: <b>{resolved}</b> &nbsp; | &nbsp; Pending: <b>{pending}</b></p>
<p>Feed: <b>{feed_status}</b> (stale={stale})</p>
<table><thead><tr><th>Agent</th><th>Forecasts</th><th>Accuracy</th><th>Brier</th><th>Qualified</th></tr></thead><tbody>{rows}</tbody></table>
<p><small>Paper validation only. Live trading is not authorized.</small></p>
</body></html>""".format(
            status=validation.get("status", "unknown"),
            qualified=validation.get("qualified_count", 0),
            required=validation.get("required", 3),
            resolved=validation.get("resolved_forecasts", 0),
            pending=validation.get("pending_forecasts", 0),
            feed_status=data.get("feed", {}).get("status", "unknown"),
            stale=data.get("feed", {}).get("stale", False),
            rows=rows,
        )

    def run_health_server(self):
        port = int(os.getenv("PORT", "8080"))
        supervisor = self

        class HealthHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in ("/", "/health", "/healthz"):
                    payload = {"status": "ok", "service": "trading-company"}
                elif self.path == "/validation":
                    payload = supervisor.validation()
                elif self.path == "/metrics":
                    payload = supervisor.metrics()
                elif self.path == "/dashboard":
                    body = supervisor.dashboard_html().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
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
        backend = os.getenv("TRADING_BACKEND", "mcx").lower()
        if backend == "mcx":
            from mcx_agent import MCXTradingCompany
            company = MCXTradingCompany()
        elif backend == "zerodha_nse":
            from nse_agent import NSETradingCompany
            company = NSETradingCompany()
        else:
            from agent import TradingCompany
            company = TradingCompany(runtime_manager=self.runtime)
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
