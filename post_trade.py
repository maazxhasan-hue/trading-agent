import json, os


def _default_state_path(filename):
    if os.path.isdir("/data"):
        return os.path.join("/data", filename)
    return filename


class PostTradeAnalyzer:
    def __init__(self, path=None):
        self.path = path or os.getenv(
            "POST_TRADE_FILE",
            _default_state_path("agent_health.json"),
        )
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

    def record(self, agent, thesis, entry, outcome, reason):
        data={}
        if os.path.exists(self.path):
            try:
                with open(self.path,encoding="utf-8") as f:data=json.load(f)
            except Exception:pass
        d=data.setdefault(agent,{"wins":0,"losses":0,"reasons":{}})
        key="wins" if outcome>0 else "losses"; d[key]+=1
        d["reasons"][reason]=d["reasons"].get(reason,0)+1
        d["last_thesis"]=thesis; d["last_entry"]=entry
        with open(self.path,"w",encoding="utf-8") as f:json.dump(data,f,indent=2)
