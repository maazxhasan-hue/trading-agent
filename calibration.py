import math, json, os
from collections import defaultdict

class CalibrationTracker:
    def __init__(self, path="agent_calibration.json"):
        self.path=path
        self.data=self._load()
    def _load(self):
        if not os.path.exists(self.path): return {}
        try:
            with open(self.path,encoding="utf-8") as f:return json.load(f)
        except Exception:return {}
    def _save(self):
        with open(self.path,"w",encoding="utf-8") as f:json.dump(self.data,f,indent=2)
    def record(self,agent,confidence,correct):
        d=self.data.setdefault(agent,{"n":0,"correct":0,"brier_sum":0.0})
        p=max(0.001,min(0.999,float(confidence)))
        d["n"]+=1; d["correct"]+=int(bool(correct)); d["brier_sum"]+=(p-int(bool(correct)))**2
        self._save()
    def stats(self,agent):
        d=self.data.get(agent,{"n":0,"correct":0,"brier_sum":0.0})
        n=d["n"]
        return {"n":n,"accuracy":d["correct"]/n if n else 0.0,"brier":d["brier_sum"]/n if n else None}
