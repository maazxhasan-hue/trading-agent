"""Isolated runtime manager for trading-company agents.

Each agent receives a private workspace, private browser profile and a
restricted terminal. Browser sessions are lazy: a browser is only started when
the deployed runtime actually has Playwright/Chromium available.
"""
from dataclasses import dataclass
from pathlib import Path
import os, shlex, shutil, subprocess

@dataclass(frozen=True)
class AgentRuntimePolicy:
    browser_enabled: bool = True
    terminal_enabled: bool = True
    network_enabled: bool = True
    allow_shell: bool = True
    max_command_seconds: int = 30

@dataclass
class AgentRuntime:
    agent_id: str
    workspace: Path
    policy: AgentRuntimePolicy
    browser_profile: Path

class AgentRuntimeManager:
    def __init__(self, root="agent_workspaces", policies=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.policies = policies or {}
        self._browser_sessions = {}
        self._runtimes = {}

    def provision(self, agent_id):
        if agent_id in self._runtimes:
            return self._runtimes[agent_id]
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in agent_id)
        workspace = self.root / safe
        profile = workspace / "browser-profile"
        workspace.mkdir(parents=True, exist_ok=True)
        profile.mkdir(parents=True, exist_ok=True)
        runtime = AgentRuntime(agent_id, workspace, self.policies.get(agent_id, AgentRuntimePolicy()), profile)
        self._runtimes[agent_id] = runtime
        return runtime

    def browser_available(self, runtime):
        if not runtime.policy.browser_enabled:
            return False
        try:
            import playwright.sync_api  # noqa: F401
            return shutil.which("chromium") is not None or shutil.which("google-chrome") is not None
        except ImportError:
            return False

    def browser_context(self, runtime):
        if not runtime.policy.browser_enabled:
            raise PermissionError("Browser capability disabled.")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed on this runtime.") from exc
        if not self.browser_available(runtime):
            raise RuntimeError("Chromium/Chrome is not installed on this runtime.")
        if runtime.agent_id in self._browser_sessions:
            return self._browser_sessions[runtime.agent_id][1]
        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(runtime.browser_profile),
            headless=os.getenv("AGENT_BROWSER_HEADLESS", "true").lower() == "true",
        )
        self._browser_sessions[runtime.agent_id] = (pw, context)
        return context

    def close_browser(self, agent_id):
        session = self._browser_sessions.pop(agent_id, None)
        if session:
            pw, context = session
            try:
                context.close()
            finally:
                pw.stop()

    def close_all(self):
        for agent_id in list(self._browser_sessions):
            self.close_browser(agent_id)

    def capability_status(self, runtime):
        return {
            "agent_id": runtime.agent_id,
            "workspace": str(runtime.workspace),
            "browser_profile": str(runtime.browser_profile),
            "browser_enabled": runtime.policy.browser_enabled,
            "browser_available": self.browser_available(runtime),
            "terminal_enabled": runtime.policy.terminal_enabled,
            "network_enabled": runtime.policy.network_enabled,
        }

    def run_terminal(self, runtime, command, timeout=None):
        if not runtime.policy.terminal_enabled or not runtime.policy.allow_shell:
            raise PermissionError("Terminal capability disabled.")
        if not command.strip():
            raise ValueError("Empty command.")
        forbidden = (";", "&&", "||", "|", ">", "<", "`", "$(", "\\")
        if any(x in command for x in forbidden):
            raise PermissionError("Compound shell commands are not allowed.")
        args = shlex.split(command)
        result = subprocess.run(args, cwd=runtime.workspace, capture_output=True, text=True,
                                timeout=timeout or runtime.policy.max_command_seconds,
                                env={k:v for k,v in os.environ.items()
                                     if k in {"PATH","HOME","LANG","LC_ALL","PYTHONPATH","TZ","TMPDIR"}})
        return {"returncode": result.returncode, "stdout": result.stdout[-12000:],
                "stderr": result.stderr[-12000:]}