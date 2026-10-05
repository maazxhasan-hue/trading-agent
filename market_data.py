import json, os, random, time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from dataclasses import dataclass

import requests

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

@dataclass
class Market:
    id: str
    question: str
    yes_token: str
    no_token: str
    yes_price: float
    no_price: float
    volume: float
    liquidity: float

S = requests.Session()
S.headers.update({
    "User-Agent": "TradingCompanyAgent/2.3 (+market-feed; contact=operator)",
    "Accept": "application/json",
})

# True when the current universe came from a cached snapshot rather than a fresh
# Gamma response. The trading engine can use this as a safety gate.
LAST_FEED_STALE = False
LAST_FEED_STATUS = "unknown"


def _cache_path():
    return os.getenv(
        "GAMMA_MARKET_CACHE_FILE",
        "/data/gamma_markets_cache.json"
        if os.path.isdir("/data") else "gamma_markets_cache.json",
    )


def _cache_max_age():
    return max(60.0, float(os.getenv("GAMMA_CACHE_MAX_AGE_SECONDS", "900")))


def feed_status():
    return {"stale": LAST_FEED_STALE, "status": LAST_FEED_STATUS}


def _retry_after(response):
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(
                0.0,
                parsedate_to_datetime(value).timestamp() - time.time(),
            )
        except Exception:
            return None


def _load_cache():
    try:
        path = _cache_path()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        rows = data.get("markets", [])
        cached_at = data.get("cached_at")
        if not isinstance(rows, list) or not rows or not cached_at:
            raise ValueError("invalid cache format")

        cached_time = datetime.fromisoformat(cached_at.replace("Z", "+00:00"))
        age = max(0.0, time.time() - cached_time.timestamp())
        if age > _cache_max_age():
            print(
                "[feed] cache expired:",
                "age=%.0fs" % age,
                "max=%.0fs" % _cache_max_age(),
            )
            return []

        print(
            "[feed] using last-good cache:",
            len(rows),
            "markets",
            "age=%.0fs" % age,
        )
        return rows
    except Exception as exc:
        print("[feed] cache unavailable:", repr(exc))
    return []


def _save_cache(rows):
    if not rows:
        return
    try:
        path = _cache_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "markets": rows,
                },
                f,
            )
        os.replace(tmp, path)
        print("[feed] saved last-good cache:", len(rows), "markets")
    except Exception as exc:
        print("[feed] cache save skipped:", repr(exc))


def _request_page(params, retries=None):
    min_interval = max(
        0.0, float(os.getenv("GAMMA_MIN_REQUEST_INTERVAL_SECONDS", "2.0"))
    )
    max_wait = max(
        1.0, float(os.getenv("GAMMA_MAX_RETRY_WAIT_SECONDS", "60"))
    )
    base = max(0.1, float(os.getenv("GAMMA_BACKOFF_BASE_SECONDS", "2")))
    retries = max(
        0, int(os.getenv("GAMMA_REQUEST_RETRIES", str(retries if retries is not None else 3)))
    )

    for attempt in range(retries + 1):
        if min_interval > 0:
            time.sleep(min_interval)

        try:
            response = S.get(
                f"{GAMMA}/markets/keyset",
                params=params,
                timeout=20,
            )

            if response.status_code == 429:
                retry_after = _retry_after(response)
                wait = (
                    retry_after
                    if retry_after is not None
                    else min(max_wait, base * (2 ** attempt))
                )
                # Never hammer the upstream. Retry-After is authoritative;
                # otherwise exponential backoff with small jitter is used.
                wait = min(max_wait, wait) + random.uniform(0, 0.5)

                if attempt >= retries:
                    print(
                        "[feed] rate limited; retries exhausted",
                        "attempt=", attempt + 1,
                        "wait=", round(wait, 2),
                    )
                    return None, "rate_limited"

                print(
                    "[feed] rate limited; retrying in %.1fs" % wait,
                    "attempt=", attempt + 1,
                )
                time.sleep(wait)
                continue

            if response.status_code >= 500:
                wait = min(max_wait, base * (2 ** attempt)) + random.uniform(0, 0.5)
                if attempt >= retries:
                    print("[feed] upstream %s; retries exhausted" % response.status_code)
                    return None, "server_error"
                print(
                    "[feed] upstream %s; retrying in %.1fs"
                    % (response.status_code, wait)
                )
                time.sleep(wait)
                continue

            response.raise_for_status()
            return response.json(), "ok"

        except requests.RequestException as exc:
            if attempt >= retries:
                print("[feed] request failed after retries:", repr(exc))
                return None, "request_error"
            wait = min(max_wait, base * (2 ** attempt)) + random.uniform(0, 0.5)
            print("[feed] request error; retrying in %.1fs" % wait)
            time.sleep(wait)

        except ValueError as exc:
            print("[feed] invalid JSON:", repr(exc))
            return None, "invalid_json"

    return None, "request_error"


def _json(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except json.JSONDecodeError:
            return []
    return x or []


def _extract_page(payload):
    # Current Gamma keyset responses are {"markets": [...], "next_cursor": "..."}.
    # Keep support for a bare list so tests/older snapshots remain compatible.
    if isinstance(payload, list):
        return payload, None
    if not isinstance(payload, dict):
        return [], None
    rows = payload.get("markets") or payload.get("items") or []
    cursor = payload.get("next_cursor") or payload.get("nextCursor")
    return rows if isinstance(rows, list) else [], cursor


def markets(max_markets=1000):
    global LAST_FEED_STALE, LAST_FEED_STATUS

    target = max(1, min(int(max_markets), 1000))
    page_size = max(
        1,
        min(int(os.getenv("GAMMA_PAGE_SIZE", "100")), target),
    )

    out = []
    cursor = None
    seen_cursors = set()
    pages = 0
    raw_rows = 0

    while len(out) < target:
        limit = min(page_size, target - len(out))
        params = {"active": "true", "closed": "false", "limit": limit}
        if cursor:
            params["after_cursor"] = cursor

        pages += 1
        payload, status = _request_page(params)
        if payload is None:
            cached = _load_cache()
            if cached:
                LAST_FEED_STALE = True
                LAST_FEED_STATUS = status + "_cache"
                parsed = _parse(cached)[:target]
                print(
                    "[feed] degraded: serving cached universe:",
                    len(parsed),
                    "markets",
                )
                return parsed

            LAST_FEED_STALE = True
            LAST_FEED_STATUS = status
            print("[feed] unavailable:", len(out), "markets")
            break

        rows, next_cursor = _extract_page(payload)
        if not rows:
            break

        raw_rows += len(rows)
        out.extend(rows)
        if len(out) >= target or len(rows) < limit or not next_cursor:
            break
        if next_cursor in seen_cursors:
            print("[feed] cursor repeated; stopping pagination")
            break

        seen_cursors.add(next_cursor)
        cursor = next_cursor

    parsed = _parse(out)[:target]

    if parsed:
        # Rank locally rather than sending an undocumented order parameter to
        # the keyset endpoint.
        parsed.sort(key=lambda m: m.volume, reverse=True)
        _save_cache(out)
        LAST_FEED_STALE = False
        LAST_FEED_STATUS = "fresh"
    else:
        LAST_FEED_STALE = True
        LAST_FEED_STATUS = "empty"

    print("[feed] universe fetched:", len(parsed), "markets", "raw_rows=", raw_rows, "pages=", pages, "target=", target, "status=", LAST_FEED_STATUS)
    return parsed


def _parse(rows):
    out = []
    for x in rows:
        if not isinstance(x, dict):
            continue
        prices = _json(x.get("outcomePrices"))
        tokens = _json(x.get("clobTokenIds") or x.get("clobTokenIDs"))
        if len(prices) < 2 or len(tokens) < 2:
            continue
        try:
            yp = float(prices[0])
            np = float(prices[1])
            if not (0.001 < yp < 0.999 and 0.001 < np < 0.999):
                continue
            out.append(
                Market(
                    str(x.get("id", "")),
                    str(x.get("question", "")),
                    str(tokens[0]),
                    str(tokens[1]),
                    yp,
                    np,
                    float(x.get("volume") or 0),
                    float(x.get("liquidity") or 0),
                )
            )
        except (TypeError, ValueError):
            continue
    return out


def price_history(token_id, interval="1d", fidelity=60):
    r = S.get(
        f"{CLOB}/prices-history",
        params={"market": token_id, "interval": interval, "fidelity": fidelity},
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("history", [])


def midpoint(token_id):
    r = S.get(
        f"{CLOB}/midpoint",
        params={"token_id": token_id},
        timeout=10,
    )
    r.raise_for_status()
    return float(r.json()["mid"])
