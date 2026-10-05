"""Isolated runtime manager for trading-company agents."""
from dataclasses import dataclass
from pathlib import Path
import os, shlex, subprocess

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

    def provision(self, agent_id):
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in agent_id)
        workspace = self.root / safe
        profile = workspace / "browser-profile"
        workspace.mkdir(parents=True, exist_ok=True)
        profile.mkdir(parents=True, exist_ok=True)
        return AgentRuntime(agent_id, workspace,
                            self.policies.get(agent_id, AgentRuntimePolicy()),
                            profile)

    def browser_context(self, runtime):
        if not runtime.policy.browser_enabled:
            raise PermissionError("Browser capability disabled.")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Install Playwright for agent browsers.") from exc
        pw = sync_playwright().start()
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(runtime.browser_profile),
            headless=os.getenv("AGENT_BROWSER_HEADLESS", "true").lower() == "true",
        )
        return pw, context

    def run_terminal(self, runtime, command, timeout=None):
        if not runtime.policy.terminal_enabled or not runtime.policy.allow_shell:
            raise PermissionError("Terminal capability disabled.")
        if not command.strip():
            raise ValueError("Empty command.")
        forbidden = (";", "&&", "||", "|", ">", "<", "`", "$(", "\\")
        if any(x in command for x in forbidden):
            raise PermissionError("Compound shell commands are not allowed.")
        args = shlex.split(command)
        result = subprocess.run(
            args, cwd=runtime.workspace, capture_output=True, text=True,
            timeout=timeout or runtime.policy.max_command_seconds,
            env={k:v for k,v in os.environ.items()
                 if k in {"PATH","HOME","LANG","LC_ALL","PYTHONPATH","TZ","TMPDIR"}},
        )
        return {"returncode": result.returncode,
                "stdout": result.stdout[-12000:],
                "stderr": result.stderr[-12000:]}
