"""Lightweight, keyless research enrichment for the paper-trading engine.

Uses public endpoints only. External evidence is treated as evidence, never truth.
X integration is intentionally optional and requires a user-supplied runtime token;
the free deployment runs without it.
"""
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
import os
from urllib.parse import quote_plus
import json
import math
import re
import xml.etree.ElementTree as ET

import requests

from market_data import price_history

NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
CLOB_BOOK = "https://clob.polymarket.com/book"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "TradingCompanyResearch/1.0"})


@dataclass
class ResearchEvidence:
    source: str
    title: str
    summary: str
    relevance: float


@dataclass
class ResearchSnapshot:
    fair_value: float
    confidence: float
    momentum: float
    mean_reversion: float
    volatility: float
    book_imbalance: float
    book_depth: float
    news_score: float
    news_count: int
    cross_market_score: float
    macro_score: float = 0.0
    crypto_score: float = 0.0
    social_score: float = 0.0
    source_status: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    research_complete: bool = True
    source_failures: list = field(default_factory=list)


def _history_signal(history):
    prices = [float(x.get("p")) for x in history if isinstance(x, dict) and x.get("p") is not None]
    if len(prices) < 8:
        return 0.0, 0.0, 0.05, 0.50, 0.50
    recent = prices[-30:]
    momentum = recent[-1] - recent[-8]
    mean = sum(recent) / len(recent)
    reversion = mean - recent[-1]
    variance = sum((p - mean) ** 2 for p in recent) / len(recent)
    volatility = math.sqrt(variance)
    # Blend independent historical features. Keep the estimate bounded.
    fair = max(0.01, min(0.99,
        0.60 * recent[-1] + 0.20 * (recent[-1] + momentum) + 0.20 * (recent[-1] + reversion)
    ))
    confidence = max(0.50, min(0.95, 0.90 - 2.0 * volatility))
    return momentum, reversion, volatility, fair, confidence


def _token_id(market):
    return str(getattr(market, "yes_token_id", "") or getattr(market, "yes_token", "") or "")


def _market_id(market):
    return str(getattr(market, "market_id", "") or getattr(market, "id", "") or "")


def _book(token_id):
    if not token_id:
        return 0.0, 0.0, 0.0
    try:
        r = SESSION.get(CLOB_BOOK, params={"token_id": token_id}, timeout=5)
        r.raise_for_status()
        data = r.json()
        bids = data.get("bids") or []
        asks = data.get("asks") or []
        bid_depth = sum(float(x.get("size", 0)) for x in bids[:10])
        ask_depth = sum(float(x.get("size", 0)) for x in asks[:10])
        total = bid_depth + ask_depth
        imbalance = (bid_depth - ask_depth) / total if total else 0.0
        return imbalance, total, 0.0
    except Exception:
        return 0.0, 0.0, 0.0


def _news(question):
    # Search only the most informative words to keep RSS URLs short.
    words = re.findall(r"[A-Za-z0-9]{3,}", question)
    query = " ".join(words[:10])
    if not query:
        return 0.0, []
    try:
        url = NEWS_RSS.format(query=quote_plus(query))
        r = SESSION.get(url, timeout=8)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        evidence = []
        for item in root.findall(".//item")[:8]:
            title = (item.findtext("title") or "").strip()
            description = re.sub(r"<[^>]+>", " ", item.findtext("description") or "").strip()
            pub = item.findtext("pubDate") or ""
            freshness = 0.5
            try:
                age = (parsedate_to_datetime(pub).timestamp())
                import time
                hours = max(0.0, (time.time() - age) / 3600)
                freshness = max(0.1, min(1.0, 1.0 - hours / 72.0))
            except Exception:
                pass
            relevance = 0.5 * freshness + 0.5 * min(1.0, len(title) / 80)
            evidence.append(ResearchEvidence("news_rss", title, description[:500], relevance))
        evidence.sort(key=lambda x: x.relevance, reverse=True)
        score = sum(e.relevance for e in evidence[:5]) / min(5, len(evidence)) if evidence else 0.0
        return score, evidence[:5]
    except Exception:
        return 0.0, []


def _cross_market(market, markets):
    # Consistency check, not a claim of executable arbitrage.
    words = set(re.findall(r"[a-z0-9]{4,}", market.question.lower()))
    peers = []
    for other in markets:
        if _market_id(other) == _market_id(market):
            continue
        other_words = set(re.findall(r"[a-z0-9]{4,}", other.question.lower()))
        overlap = len(words & other_words) / max(1, len(words | other_words))
        if overlap >= 0.30:
            peers.append(other.yes_price)
    if not peers:
        return 0.0
    mean = sum(peers) / len(peers)
    return max(-1.0, min(1.0, (mean - market.yes_price) / 0.10))



def _macro_event(question):
    macro_terms = "interest rates inflation central bank jobs GDP election regulation court approval deadline"
    score, evidence = _news(question + " " + macro_terms)
    return score, evidence


def _crypto(question):
    text = question.lower()
    assets = []
    for key, asset in (("bitcoin", "bitcoin"), ("btc", "bitcoin"),
                       ("ethereum", "ethereum"), ("eth", "ethereum"),
                       ("solana", "solana"), ("sol", "solana")):
        if key in text and asset not in assets:
            assets.append(asset)
    if not assets:
        return 0.0, "not_applicable"
    try:
        params = {
            "ids": ",".join(assets),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        }
        r = SESSION.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params=params,
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        changes = [
            float(data[a].get("usd_24h_change", 0.0))
            for a in assets
            if isinstance(data.get(a), dict)
        ]
        if not changes:
            return 0.0, "unavailable"
        return max(-1.0, min(1.0, sum(changes) / len(changes) / 10.0)), "ok"
    except Exception:
        return 0.0, "unavailable"


def _social(question):
    token = os.getenv("X_BEARER_TOKEN", "").strip()
    if not token:
        return 0.0, "unavailable_no_token"
    try:
        query = " ".join(re.findall(r"[A-Za-z0-9_]{3,}", question)[:8])
        if not query:
            return 0.0, "unavailable_no_query"
        r = SESSION.get(
            "https://api.x.com/2/tweets/search/recent",
            params={"query": query + " -is:retweet", "max_results": 10},
            headers={"Authorization": "Bearer " + token},
            timeout=8,
        )
        r.raise_for_status()
        rows = r.json().get("data") or []
        return min(1.0, len(rows) / 10.0), "ok"
    except Exception:
        return 0.0, "unavailable_request_error"

def research_market(market, markets):
    warnings = []
    try:
        history = price_history(_token_id(market), interval="1d", fidelity=60)
        momentum, reversion, volatility, historical_fair, historical_conf = _history_signal(history)
    except Exception:
        history = []
        momentum = reversion = 0.0
        volatility = 0.05
        historical_fair = market.yes_price
        historical_conf = 0.50
        warnings.append("historical_data_unavailable")

    token_id = _token_id(market)
    imbalance, depth, _ = _book(token_id)
    news_score, news_evidence = _news(market.question)
    macro_score, macro_evidence = _macro_event(market.question)
    crypto_score, crypto_status = _crypto(market.question)
    social_score, social_status = _social(market.question)
    cross = _cross_market(market, markets)
    evidence = (news_evidence + macro_evidence)[:10]

    # Independent fair-value components. Do not let news/social evidence directly
    # become a probability; it only adjusts confidence and creates an audit trail.
    fair = max(0.01, min(0.99,
        0.55 * historical_fair +
        0.20 * market.yes_price +
        0.10 * (market.yes_price + 0.05 * cross) +
        0.15 * (market.yes_price + 0.05 * imbalance)
    ))
    confidence = max(0.50, min(0.95,
        0.55 * historical_conf +
        0.20 * min(0.95, 0.50 + abs(imbalance) * 0.45) +
        0.10 * min(0.95, 0.50 + news_score * 0.45) +
        0.10 * min(0.95, 0.50 + macro_score * 0.45) +
        0.05 * min(0.95, 0.50 + abs(crypto_score) * 0.45) +
        0.05 * min(0.95, 0.50 + abs(social_score) * 0.45) +
        0.10 * min(0.95, 0.50 + abs(cross) * 0.45)
    ))
    applicable = {"market_history": True, "order_book": True, "news": True, "macro_event": True}
    if crypto_status == "not_applicable":
        applicable["crypto"] = False
    status = {
        "market_history": bool(history), "order_book": bool(depth),
        "news": bool(news_evidence), "macro_event": bool(macro_evidence),
        "crypto": crypto_status == "ok",
    }
    failures = [name for name, required in applicable.items() if required and not status.get(name, False)]
    complete = not failures
    if failures:
        warnings.extend("research_source_unavailable:" + name for name in failures)

    return ResearchSnapshot(
        fair, confidence, momentum, reversion, volatility, imbalance, depth,
        news_score, len(news_evidence), cross,
        macro_score, crypto_score, social_score,
        {"market_history": bool(history), "order_book": bool(depth),
         "news": bool(news_evidence), "macro_event": bool(macro_evidence),
         "crypto": crypto_status == "ok", "x_social": social_status == "ok",
         "cross_market": bool(cross)},
        evidence, warnings, complete, failures
    )
