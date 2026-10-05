import json,os
class PostTradeAnalyzer:
    def __init__(self,path="agent_health.json"):
        self.path=path
    def record(self,agent,thesis,entry,outcome,reason):
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
