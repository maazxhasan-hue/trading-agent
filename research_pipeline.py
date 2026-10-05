"""Research enrichment, provenance and freshness gates for paper trading.

Public endpoints are evidence sources, not truth. Required-source gates prevent
the engine from trading when critical evidence is unavailable or stale.
"""
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
import os
from urllib.parse import quote_plus
import time
import json
import math
import re
import xml.etree.ElementTree as ET

import requests

from market_data import price_history
from event_calendar import fetch_events
from fair_value import FairValueModel
from research_quality import ResearchQuality

NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
CLOB_BOOK = "https://clob.polymarket.com/book"
MAX_SOURCE_AGE = int(os.getenv("MAX_RESEARCH_AGE_SECONDS", "900"))

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "TradingCompanyResearch/2.1"})


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
    source_timestamps: dict = field(default_factory=dict)
    source_ages_seconds: dict = field(default_factory=dict)
    provenance: dict = field(default_factory=dict)
    event_count: int = 0
    event_status: str = "not_configured"
    fair_value_components: dict = field(default_factory=dict)


def _history_signal(history):
    prices = [float(x.get("p")) for x in history
              if isinstance(x, dict) and x.get("p") is not None]
    if len(prices) < 8:
        return 0.0, 0.0, 0.05, 0.50, 0.50
    recent = prices[-30:]
    momentum = recent[-1] - recent[-8]
    mean = sum(recent) / len(recent)
    reversion = mean - recent[-1]
    variance = sum((p - mean) ** 2 for p in recent) / len(recent)
    volatility = math.sqrt(variance)
    fair = max(0.01, min(0.99,
        0.60 * recent[-1]
        + 0.20 * (recent[-1] + momentum)
        + 0.20 * (recent[-1] + reversion)
    ))
    confidence = max(0.50, min(0.95, 0.90 - 2.0 * volatility))
    return momentum, reversion, volatility, fair, confidence


def _token_id(market):
    return str(getattr(market, "yes_token_id", "")
               or getattr(market, "yes_token", "") or "")


def _market_id(market):
    return str(getattr(market, "market_id", "")
               or getattr(market, "id", "") or "")


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
            description = re.sub(
                r"<[^>]+>", " ", item.findtext("description") or ""
            ).strip()
            pub = item.findtext("pubDate") or ""
            freshness = 0.5
            try:
                age = parsedate_to_datetime(pub).timestamp()
                hours = max(0.0, (time.time() - age) / 3600)
                freshness = max(0.1, min(1.0, 1.0 - hours / 72.0))
            except Exception:
                pass
            relevance = 0.5 * freshness + 0.5 * min(1.0, len(title) / 80)
            evidence.append(ResearchEvidence(
                "news_rss", title, description[:500], relevance
            ))
        evidence.sort(key=lambda x: x.relevance, reverse=True)
        score = (
            sum(e.relevance for e in evidence[:5]) / min(5, len(evidence))
            if evidence else 0.0
        )
        return score, evidence[:5]
    except Exception:
        return 0.0, []


def _cross_market(market, markets):
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
    macro_terms = (
        "interest rates inflation central bank jobs GDP election "
        "regulation court approval deadline"
    )
    score, evidence = _news(question + " " + macro_terms)
    return score, evidence


def _crypto(question):
    text = question.lower()
    assets = []
    for key, asset in (
        ("bitcoin", "bitcoin"), ("btc", "bitcoin"),
        ("ethereum", "ethereum"), ("eth", "ethereum"),
        ("solana", "solana"), ("sol", "solana"),
    ):
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
            params=params, timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        changes = [
            float(data[a].get("usd_24h_change", 0.0))
            for a in assets if isinstance(data.get(a), dict)
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
    quality = ResearchQuality()
    fetched_at = time.time()

    try:
        history = price_history(_token_id(market), interval="1d", fidelity=60)
        momentum, reversion, volatility, historical_fair, historical_conf = _history_signal(history)
        quality.add("market_history", bool(history), fetched_at, len(history), MAX_SOURCE_AGE)
    except Exception:
        history = []
        momentum = reversion = 0.0
        volatility = 0.05
        historical_fair = market.yes_price
        historical_conf = 0.50
        quality.add("market_history", False, fetched_at, 0, MAX_SOURCE_AGE)
        warnings.append("historical_data_unavailable")

    token_id = _token_id(market)
    imbalance, depth, _ = _book(token_id)
    quality.add("order_book", bool(depth), fetched_at, 1 if depth else 0, MAX_SOURCE_AGE)

    news_score, news_evidence = _news(market.question)
    quality.add("news", bool(news_evidence), fetched_at, len(news_evidence), MAX_SOURCE_AGE)

    macro_score, macro_evidence = _macro_event(market.question)
    quality.add("macro_event", bool(macro_evidence), fetched_at, len(macro_evidence), MAX_SOURCE_AGE)

    events, event_status = fetch_events(market.question)
    event_required = os.getenv("REQUIRE_EVENT_CALENDAR", "false").lower() == "true"
    event_ok = bool(events) or event_status == "ok_no_events"
    if event_required:
        quality.add("event_calendar", event_ok, fetched_at, len(events), MAX_SOURCE_AGE)
    else:
        quality.add("event_calendar", True, fetched_at, len(events), MAX_SOURCE_AGE)

    crypto_score, crypto_status = _crypto(market.question)
    crypto_required = crypto_status != "not_applicable"
    quality.add("crypto", crypto_status == "ok" if crypto_required else True,
                fetched_at, 1 if crypto_status == "ok" else 0, MAX_SOURCE_AGE)

    social_score, social_status = _social(market.question)
    quality.add("x_social", social_status == "ok" or not os.getenv("REQUIRE_X_SOCIAL", "").lower() == "true",
                fetched_at, 1 if social_status == "ok" else 0, MAX_SOURCE_AGE)

    cross = _cross_market(market, markets)
    # A market with no meaningful peer is not a failed source.
    quality.add("cross_market", True, fetched_at, 1 if cross else 0, MAX_SOURCE_AGE)

    history_values = [
        float(x.get("p")) for x in history
        if isinstance(x, dict) and x.get("p") is not None
    ]
    fv = FairValueModel().estimate(
        current=market.yes_price,
        history_fair=historical_fair,
        history_confidence=historical_conf,
        volatility=volatility,
        book_imbalance=imbalance,
        cross_market_score=cross,
        news_score=news_score,
        macro_score=macro_score,
        crypto_score=crypto_score,
        social_score=social_score,
        history=history_values,
    )
    evidence = (news_evidence + macro_evidence + [
        ResearchEvidence("event_calendar", e.title, e.start, e.relevance)
        for e in events
    ])[:12]

    failures = list(dict.fromkeys(quality.failures))
    complete = not failures
    warnings.extend(quality.warnings)
    if event_status == "unavailable_no_calendar_url" and not event_required:
        warnings.append("event_calendar_not_configured_optional")
    if social_status != "ok" and os.getenv("REQUIRE_X_SOCIAL", "").lower() == "true":
        warnings.append("x_social_required_but_unavailable")

    status = quality.status()
    status["crypto"] = crypto_status == "ok" if crypto_required else True
    status["x_social"] = social_status == "ok"
    status["cross_market"] = bool(cross)

    return ResearchSnapshot(
        fair_value=fv.value,
        confidence=fv.confidence,
        momentum=momentum,
        mean_reversion=reversion,
        volatility=volatility,
        book_imbalance=imbalance,
        book_depth=depth,
        news_score=news_score,
        news_count=len(news_evidence),
        cross_market_score=cross,
        macro_score=macro_score,
        crypto_score=crypto_score,
        social_score=social_score,
        source_status=status,
        evidence=evidence,
        warnings=warnings,
        research_complete=complete,
        source_failures=failures,
        source_timestamps=quality.timestamps(),
        source_ages_seconds=quality.ages(),
        provenance=quality.provenance(),
        event_count=len(events),
        event_status=event_status,
        fair_value_components=fv.components,
    )
