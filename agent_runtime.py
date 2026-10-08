"""Per-agent isolated runtime for research and diagnostics."""
from dataclasses import dataclass
from pathlib import Path
import json, os, shlex, shutil, subprocess, time

DEFAULT_COMMANDS = frozenset({
    "cat", "date", "find", "git", "grep", "head", "ls", "python",
    "python3", "pwd", "sed", "tail", "which",
})

@dataclass(frozen=True)
class AgentRuntimePolicy:
    browser_enabled: bool = True
    terminal_enabled: bool = True
    network_enabled: bool = True
    allow_shell: bool = True
    max_command_seconds: int = 30
    allowed_commands: frozenset = DEFAULT_COMMANDS

@dataclass
class AgentRuntime:
    agent_id: str
    workspace: Path
    policy: AgentRuntimePolicy
    browser_profile: Path

class AgentRuntimeManager:
    def __init__(self, root="agent_workspaces", policies=None, audit_file=None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.policies = policies or {}
        self.audit_file = Path(audit_file or os.getenv(
            "AGENT_RUNTIME_AUDIT_FILE", "logs/agent_runtime_audit.jsonl"))
        self._browser_sessions = {}
        self._runtimes = {}

    def _audit(self, event, **payload):
        self.audit_file.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"time": time.time(), "event": event, **payload}) + "\n")

    def provision(self, agent_id):
        if agent_id in self._runtimes:
            return self._runtimes[agent_id]
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in agent_id)
        workspace = self.root / safe
        profile = workspace / "browser-profile"
        workspace.mkdir(parents=True, exist_ok=True)
        profile.mkdir(parents=True, exist_ok=True)
        runtime = AgentRuntime(agent_id, workspace,
                               self.policies.get(agent_id, AgentRuntimePolicy()), profile)
        self._runtimes[agent_id] = runtime
        self._audit("provision", agent_id=agent_id, workspace=str(workspace))
        return runtime

    def browser_available(self, runtime):
        if not runtime.policy.browser_enabled:
            return False
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            return False
        executable = os.getenv("AGENT_BROWSER_EXECUTABLE_PATH")
        if executable:
            return Path(executable).exists()
        return any(shutil.which(x) for x in ("chromium", "chromium-browser", "google-chrome"))

    def browser_context(self, runtime):
        if not runtime.policy.browser_enabled:
            raise PermissionError("Browser capability disabled.")
        from playwright.sync_api import sync_playwright
        if not self.browser_available(runtime):
            raise RuntimeError("Chromium/Chrome is not installed.")
        if runtime.agent_id in self._browser_sessions:
            return self._browser_sessions[runtime.agent_id][1]
        pw = sync_playwright().start()
        kwargs = {
            "user_data_dir": str(runtime.browser_profile),
            "headless": os.getenv("AGENT_BROWSER_HEADLESS", "true").lower() == "true",
        }
        executable = os.getenv("AGENT_BROWSER_EXECUTABLE_PATH")
        if executable:
            kwargs["executable_path"] = executable
        context = pw.chromium.launch_persistent_context(**kwargs)
        self._browser_sessions[runtime.agent_id] = (pw, context)
        self._audit("browser_open", agent_id=runtime.agent_id)
        return context

    def close_browser(self, agent_id):
        session = self._browser_sessions.pop(agent_id, None)
        if session:
            pw, context = session
            try:
                context.close()
            finally:
                pw.stop()
            self._audit("browser_close", agent_id=agent_id)

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
            "terminal_isolated_workspace": True,
            "network_enabled": runtime.policy.network_enabled,
            "order_execution_access": False,
        }

    def run_terminal(self, runtime, command, timeout=None):
        if not runtime.policy.terminal_enabled or not runtime.policy.allow_shell:
            raise PermissionError("Terminal capability disabled.")
        if not command.strip():
            raise ValueError("Empty command.")
        if any(x in command for x in (";", "&&", "||", "|", ">", "<", "`", "$(", "\\", "\n")):
            raise PermissionError("Compound shell commands are not allowed.")
        args = shlex.split(command)
        if not args or args[0] not in runtime.policy.allowed_commands:
            raise PermissionError("Command is not in the agent terminal allowlist.")
        env = {k: v for k, v in os.environ.items()
               if k in {"PATH", "HOME", "LANG", "LC_ALL", "PYTHONPATH", "TZ", "TMPDIR"}}
        result = subprocess.run(args, cwd=runtime.workspace, capture_output=True, text=True,
                                timeout=timeout or runtime.policy.max_command_seconds,
                                env=env, shell=False)
        self._audit("terminal", agent_id=runtime.agent_id,
                    command=args[0], returncode=result.returncode)
        return {"returncode": result.returncode,
                "stdout": result.stdout[-12000:], "stderr": result.stderr[-12000:]}
