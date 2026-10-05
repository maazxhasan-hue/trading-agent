import json, os, random, time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import requests
from dataclasses import dataclass
GAMMA="https://gamma-api.polymarket.com"
CLOB="https://clob.polymarket.com"
@dataclass
class Market:
    id:str; question:str; yes_token:str; no_token:str; yes_price:float; no_price:float; volume:float; liquidity:float
S=requests.Session()
S.headers.update({"User-Agent":"TradingCompanyAgent/2.2 (+market-feed)"})

def _cache_path():
    return os.getenv("GAMMA_MARKET_CACHE_FILE",
        "/data/gamma_markets_cache.json" if os.path.isdir("/data") else "gamma_markets_cache.json")

def _retry_after(response):
    value=response.headers.get("Retry-After")
    if not value:return None
    try:return max(0.0,float(value))
    except ValueError:
        try:return max(0.0,parsedate_to_datetime(value).timestamp()-time.time())
        except Exception:return None

def _load_cache():
    try:
        with open(_cache_path(),encoding="utf-8") as f:data=json.load(f)
        rows=data.get("markets",[])
        if isinstance(rows,list) and rows:
            print("[feed] using last-good cache:",len(rows),"markets","cached_at=",data.get("cached_at","unknown"))
            return rows
    except Exception as exc:
        print("[feed] cache unavailable:",repr(exc))
    return []

def _save_cache(rows):
    if not rows:return
    try:
        path=_cache_path(); os.makedirs(os.path.dirname(path) or ".",exist_ok=True)
        with open(path,"w",encoding="utf-8") as f:
            json.dump({"cached_at":datetime.now(timezone.utc).isoformat(),"markets":rows},f)
    except Exception as exc:
        print("[feed] cache save skipped:",repr(exc))

def _request_page(params,retries=4):
    min_interval=float(os.getenv("GAMMA_MIN_REQUEST_INTERVAL_SECONDS","1.0"))
    max_wait=float(os.getenv("GAMMA_MAX_RETRY_WAIT_SECONDS","60"))
    base=float(os.getenv("GAMMA_BACKOFF_BASE_SECONDS","2"))
    for attempt in range(retries+1):
        if min_interval>0: time.sleep(min_interval)
        try:
            response=S.get(f"{GAMMA}/markets",params=params,timeout=20)
            if response.status_code==429:
                retry_after=_retry_after(response)
                wait=(retry_after if retry_after is not None else min(30.0,base*(2**attempt)))+random.uniform(0,0.5)
                if attempt>=retries or wait>max_wait:
                    print("[feed] rate limited; stopping retries","attempt=",attempt+1,"wait=",round(wait,2))
                    return None,"rate_limited"
                print("[feed] rate limited; retrying in %.1fs"%wait,"attempt=",attempt+1)
                time.sleep(wait); continue
            if response.status_code>=500:
                wait=min(max_wait,base*(2**attempt))+random.uniform(0,0.5)
                if attempt>=retries:return None,"server_error"
                print("[feed] upstream %s; retrying in %.1fs"%(response.status_code,wait))
                time.sleep(wait); continue
            response.raise_for_status()
            return response.json(),"ok"
        except requests.RequestException as exc:
            if attempt>=retries:
                print("[feed] request failed after retries:",repr(exc)); return None,"request_error"
            wait=min(max_wait,base*(2**attempt))+random.uniform(0,0.5)
            print("[feed] request error; retrying in %.1fs"%wait); time.sleep(wait)
        except ValueError as exc:
            print("[feed] invalid JSON:",repr(exc)); return None,"invalid_json"
    return None,"request_error"
def _json(x):
    if isinstance(x,str):
        try:return json.loads(x)
        except json.JSONDecodeError:return []
    return x or []
def markets(max_markets=1000):
    target=max(1,min(int(max_markets),1000))
    page_size=max(25,min(int(os.getenv("GAMMA_PAGE_SIZE","100")),target))
    out=[]; offset=0
    while len(out)<target:
        limit=min(page_size,target-len(out))
        rows,status=_request_page({"active":"true","closed":"false","limit":limit,"offset":offset,
                                   "order":"volume_24hr","ascending":"false"})
        if rows is None:
            cached=_load_cache()
            if cached:return _parse(cached)[:target]
            print("[feed] unavailable:",len(out),"markets"); break
        if not isinstance(rows,list) or not rows:break
        out.extend(rows)
        if len(rows)<limit:break
        offset+=limit
    parsed=_parse(out)[:target]
    if out:
        _save_cache(out)
    print("[feed] universe fetched:",len(parsed),"markets")
    return parsed

def _parse(rows):
    out=[]
    for x in rows:
        prices=_json(x.get("outcomePrices")); tokens=_json(x.get("clobTokenIds") or x.get("clobTokenIDs"))
        if len(prices)<2 or len(tokens)<2:continue
        try:
            yp=float(prices[0]); np=float(prices[1])
            if not (0.001<yp<0.999 and 0.001<np<0.999):continue
            out.append(Market(str(x.get("id","")),str(x.get("question","")),str(tokens[0]),str(tokens[1]),
                              yp,np,float(x.get("volume") or 0),float(x.get("liquidity") or 0)))
        except (TypeError,ValueError):continue
    return out

def price_history(token_id, interval="1d", fidelity=60):
    r=S.get(f"{CLOB}/prices-history",params={"market":token_id,"interval":interval,"fidelity":fidelity},timeout=20); r.raise_for_status()
    return r.json().get("history",[])
def midpoint(token_id):
    r=S.get(f"{CLOB}/midpoint",params={"token_id":token_id},timeout=10); r.raise_for_status()
    return float(r.json()["mid"])
