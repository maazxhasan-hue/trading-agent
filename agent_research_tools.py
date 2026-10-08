"""Read-only browser research for isolated agents."""
from dataclasses import dataclass
from agent_runtime import AgentRuntimeManager

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
        if len(url) > 2048:
            raise ValueError("URL is too long.")
        runtime = self.manager.provision(agent_id)
        page = None
        try:
            context = self.manager.browser_context(runtime)
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            return BrowserResearchResult(url, page.title(),
                page.locator("body").inner_text(timeout=10000)[:max_chars], True)
        except Exception as exc:
            return BrowserResearchResult(url, "", "", False, repr(exc))
        finally:
            if page is not None:
                page.close()
