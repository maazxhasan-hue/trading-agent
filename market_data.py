import json, requests
from dataclasses import dataclass
GAMMA="https://gamma-api.polymarket.com"
CLOB="https://clob.polymarket.com"
@dataclass
class Market:
    id:str; question:str; yes_token:str; no_token:str; yes_price:float; no_price:float; volume:float; liquidity:float
S=requests.Session(); S.headers.update({"User-Agent":"TradingCompanyAgent/1.1"})
def _json(x):
    if isinstance(x,str):
        try:return json.loads(x)
        except json.JSONDecodeError:return []
    return x or []
def markets(max_markets=1000):
    out=[]; offset=0
    while len(out)<max_markets:
        limit=min(500,max_markets-len(out))
        r=S.get(f"{GAMMA}/markets",params={"active":"true","closed":"false","limit":limit,"offset":offset,"order":"volume_24hr","ascending":"false"},timeout=20); r.raise_for_status()
        rows=r.json()
        if not rows: break
        for x in rows:
            prices=_json(x.get("outcomePrices")); tokens=_json(x.get("clobTokenIds"))
            if len(prices)<2 or len(tokens)<2: continue
            try:
                yp=float(prices[0]); np=float(prices[1])
                if not (0.001<yp<0.999 and 0.001<np<0.999): continue
                out.append(Market(str(x.get("id","")),str(x.get("question","")),str(tokens[0]),str(tokens[1]),yp,np,float(x.get("volume") or 0),float(x.get("liquidity") or 0)))
            except (TypeError,ValueError): continue
            if len(out)>=max_markets: break
        if len(rows)<limit: break
        offset+=limit
    return out
def price_history(token_id, interval="1d", fidelity=60):
    r=S.get(f"{CLOB}/prices-history",params={"market":token_id,"interval":interval,"fidelity":fidelity},timeout=20); r.raise_for_status()
    return r.json().get("history",[])
def midpoint(token_id):
    r=S.get(f"{CLOB}/midpoint",params={"token_id":token_id},timeout=10); r.raise_for_status()
    return float(r.json()["mid"])
