"""Lightweight, keyless research enrichment for the paper-trading engine.

Uses public endpoints only. External evidence is treated as evidence, never truth.
X integration is intentionally optional and requires a user-supplied runtime token;
the free deployment runs without it.
"""
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
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
    evidence: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


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


def _book(token_id):
    if not token_id:
        return 0.0, 0.0, 0.0
    try:
        r = SESSION.get(CLOB_BOOK, params={"token_id": token_id}, timeout=8)
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
        if other.market_id == market.market_id:
            continue
        other_words = set(re.findall(r"[a-z0-9]{4,}", other.question.lower()))
        overlap = len(words & other_words) / max(1, len(words | other_words))
        if overlap >= 0.30:
            peers.append(other.yes_price)
    if not peers:
        return 0.0
    mean = sum(peers) / len(peers)
    return max(-1.0, min(1.0, (mean - market.yes_price) / 0.10))


def research_market(market, markets):
    warnings = []
    try:
        history = price_history(market.yes_token, interval="1d", fidelity=60)
        momentum, reversion, volatility, historical_fair, historical_conf = _history_signal(history)
    except Exception:
        history = []
        momentum = reversion = 0.0
        volatility = 0.05
        historical_fair = market.yes_price
        historical_conf = 0.50
        warnings.append("historical_data_unavailable")

    imbalance, depth, _ = _book(market.yes_token)
    news_score, evidence = _news(market.question)
    cross = _cross_market(market, markets)

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
        0.15 * min(0.95, 0.50 + news_score * 0.45) +
        0.10 * min(0.95, 0.50 + abs(cross) * 0.45)
    ))
    return ResearchSnapshot(
        fair, confidence, momentum, reversion, volatility, imbalance, depth,
        news_score, len(evidence), cross, evidence, warnings
    )
