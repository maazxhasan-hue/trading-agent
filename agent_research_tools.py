"""Optional per-agent browser/terminal research tools.

These tools are read-only research helpers. They never place orders or access
credentials. Browser profiles are isolated per agent by AgentRuntimeManager.
"""
from dataclasses import dataclass
from agent_runtime import AgentRuntimeManager, AgentRuntime

@dataclass
class BrowserResearchResult:
    url: str
    title: str
    text: str
    ok: bool
    error: str = ""

class AgentResearchTools:
    def __init__(self, manager=None):
        self.manager = manager or AgentRuntimeManager()

    def fetch_page(self, agent_id, url, max_chars=6000):
        if not (url.startswith("https://") or url.startswith("http://")):
            raise ValueError("Only HTTP(S) URLs are allowed.")
        runtime = self.manager.provision(agent_id)
        pw = context = None
        try:
            pw, context = self.manager.browser_context(runtime)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            title = page.title()
            text = page.locator("body").inner_text(timeout=10000)
            return BrowserResearchResult(url, title, text[:max_chars], True)
        except Exception as exc:
            return BrowserResearchResult(url, "", "", False, repr(exc))
        finally:
            if context is not None:
                context.close()
            if pw is not None:
                pw.stop()
