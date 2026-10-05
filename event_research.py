import re
from dataclasses import dataclass

@dataclass
class Evidence:
    source:str
    title:str
    text:str
    relevance:float

class EventResearch:
    """Accepts already-authorized text/news evidence; it never claims web access."""
    KEYWORDS=("election","rate","inflation","court","war","vote","earnings","deadline","approval","launch")
    def score(self,evidence):
        if not evidence:return 0.0,[]
        scored=[]
        for e in evidence:
            blob=(e.title+" "+e.text).lower()
            hits=sum(1 for k in self.KEYWORDS if k in blob)
            relevance=min(1.0,hits/3)
            scored.append((relevance,e))
        scored.sort(key=lambda x:x[0],reverse=True)
        return sum(x[0] for x in scored[:5])/min(5,len(scored)),[x[1] for x in scored[:5]]
