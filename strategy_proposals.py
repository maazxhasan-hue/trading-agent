"""Broker-independent, auditable outputs from an individual strategy."""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


_COST_COMPONENTS = ("fees", "spread", "slippage", "taxes")
_SECRET_FEATURE_MARKERS = (
    "api_key", "apikey", "authorization", "cookie", "jwt", "password",
    "pin", "refresh", "secret", "totp",
)
_FEATURE_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")
_STRATEGIES = {
    "momentum-v3": ("momentum", "momentum-v3"),
    "mean_reversion-v3": ("mean_reversion", "mean-reversion-v3"),
    "event_driven-v3": ("event_driven", "event-driven-v3"),
    "mcx_commodity_specialist-v3": ("mcx_commodity_specialist", "mcx-commodity-specialist-v3"),
    "cross_market_arbitrage-v3": ("cross_market_arbitrage", "cross-market-arbitrage-v3"),
}


def _finite_number(value, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number")
    return number


def _nonempty(value, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} is required")
    return text


@dataclass(frozen=True)
class StrategyProposal:
    """One directional strategy idea, with explicit price and cost assumptions.

    Edge and cost amounts are per tradable unit, in the instrument's quote
    currency. Proposals contain no broker credentials or execution client.
    """

    strategy_id: str
    strategy_version: str
    data_version: str
    validation_version: str
    market_id: str
    tradingsymbol: str
    exchange: str
    timeframe: str
    lot_size: int
    direction: int
    entry_price: float
    stop_price: float
    target_price: float
    confidence: float
    rationale: str
    features: Mapping[str, float]
    signal_timestamp: float
    data_timestamp: float
    max_data_age_seconds: float
    estimated_gross_edge: float
    estimated_costs: Mapping[str, float]

    def __post_init__(self):
        for name in (
            "strategy_id", "strategy_version", "data_version", "validation_version",
            "market_id", "tradingsymbol", "timeframe",
        ):
            object.__setattr__(self, name, _nonempty(getattr(self, name), name))

        exchange = _nonempty(self.exchange, "exchange").upper()
        if exchange not in {"NSE", "MCX"}:
            raise ValueError("exchange must be NSE or MCX")
        object.__setattr__(self, "exchange", exchange)

        if type(self.lot_size) is not int or self.lot_size <= 0:
            raise ValueError("lot_size must be a positive integer")
        if type(self.direction) is not int or self.direction not in {-1, 1}:
            raise ValueError("direction must be -1 or 1")

        for name in ("entry_price", "stop_price", "target_price"):
            number = _finite_number(getattr(self, name), name)
            if number <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, number)
        if self.direction > 0 and not self.stop_price < self.entry_price < self.target_price:
            raise ValueError("long proposal requires stop < entry < target")
        if self.direction < 0 and not self.target_price < self.entry_price < self.stop_price:
            raise ValueError("short proposal requires target < entry < stop")

        confidence = _finite_number(self.confidence, "confidence")
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "confidence", confidence)

        rationale = _nonempty(self.rationale, "rationale")
        if len(rationale) > 500:
            raise ValueError("rationale must be at most 500 characters")
        object.__setattr__(self, "rationale", rationale)

        if not isinstance(self.features, Mapping):
            raise ValueError("features must be a numeric mapping")
        features = {}
        for key, value in self.features.items():
            if not isinstance(key, str) or not _FEATURE_NAME.fullmatch(key):
                raise ValueError("feature names must be simple identifiers")
            if any(marker in key.lower() for marker in _SECRET_FEATURE_MARKERS):
                raise ValueError("secret-shaped feature names are not allowed")
            features[key] = _finite_number(value, f"feature {key}")
        object.__setattr__(self, "features", MappingProxyType(features))

        for name in ("signal_timestamp", "data_timestamp", "max_data_age_seconds"):
            number = _finite_number(getattr(self, name), name)
            if number < 0:
                raise ValueError(f"{name} must not be negative")
            object.__setattr__(self, name, number)
        if self.max_data_age_seconds <= 0:
            raise ValueError("max_data_age_seconds must be positive")
        if self.signal_timestamp < self.data_timestamp:
            raise ValueError("signal timestamp cannot precede its market data")

        gross_edge = _finite_number(self.estimated_gross_edge, "estimated_gross_edge")
        if gross_edge < 0:
            raise ValueError("estimated_gross_edge must not be negative")
        object.__setattr__(self, "estimated_gross_edge", gross_edge)

        if not isinstance(self.estimated_costs, Mapping):
            raise ValueError("estimated_costs must be a mapping")
        missing = set(_COST_COMPONENTS) - set(self.estimated_costs)
        if missing:
            raise ValueError("estimated_costs must include fees, spread, slippage, and taxes")
        costs = {}
        for key, value in self.estimated_costs.items():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("cost names must be nonempty strings")
            amount = _finite_number(value, f"cost {key}")
            if amount < 0:
                raise ValueError("estimated costs must not be negative")
            costs[key] = amount
        object.__setattr__(self, "estimated_costs", MappingProxyType(costs))

    @property
    def estimated_net_edge(self) -> float:
        return self.estimated_gross_edge - sum(self.estimated_costs.values())

    @property
    def intent_id(self) -> str:
        payload = self.to_dict(include_identity=False)
        # Re-evaluating one unchanged market snapshot must keep the same
        # idempotency key even if the agent's wall-clock time has advanced.
        payload.pop("signal_timestamp", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return "strategy-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]

    def is_fresh(self, *, now: float) -> bool:
        """Return false for stale or future-dated source data."""
        current = _finite_number(now, "now")
        age = current - self.data_timestamp
        return 0 <= age <= self.max_data_age_seconds

    def to_dict(self, *, include_identity: bool = True) -> dict:
        row = {
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "data_version": self.data_version,
            "validation_version": self.validation_version,
            "market_id": self.market_id,
            "tradingsymbol": self.tradingsymbol,
            "exchange": self.exchange,
            "timeframe": self.timeframe,
            "lot_size": self.lot_size,
            "direction": self.direction,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "features": dict(self.features),
            "signal_timestamp": self.signal_timestamp,
            "data_timestamp": self.data_timestamp,
            "max_data_age_seconds": self.max_data_age_seconds,
            "estimated_gross_edge": self.estimated_gross_edge,
            "estimated_costs": dict(self.estimated_costs),
            "estimated_net_edge": self.estimated_net_edge,
        }
        if include_identity:
            row["intent_id"] = self.intent_id
        return row


def proposal_from_vote(vote: float, **fields) -> StrategyProposal | None:
    """Convert a non-neutral signed strategy vote into a proposal.

    The caller supplies the explicit market, risk, time, and cost assumptions.
    A neutral vote is no proposal and cannot be turned into an order intent.
    """
    value = _finite_number(vote, "vote")
    if value == 0:
        return None
    fields.pop("direction", None)
    return StrategyProposal(direction=1 if value > 0 else -1, **fields)


def proposals_from_votes(
    *,
    votes: Mapping[str, float],
    market,
    features: Mapping[str, float],
    costs_bps: Mapping[str, float] | None,
    data_version: str,
    validation_version: str,
    timeframe: str,
    signal_timestamp: float,
    max_data_age_seconds: float,
) -> dict[str, list]:
    """Build auditable proposals from the existing NSE/MCX vote snapshot.

    Cost inputs are explicit round-trip basis points. An incomplete estimate or
    missing source timestamp rejects the proposal rather than assuming zero.
    The volatility-scaled gross edge is a research proxy, not validated EV.
    """
    proposals: list[StrategyProposal] = []
    rejections: list[dict[str, str]] = []

    def reject(strategy_id: str, reason: str):
        rejections.append({"strategy_id": strategy_id, "reason": reason})

    try:
        timestamp = _finite_number(getattr(market, "quote_timestamp", None), "data timestamp")
    except ValueError:
        timestamp = None

    try:
        entry = _finite_number(getattr(market, "last_price", None), "entry price")
        volatility = _finite_number(features.get("vol"), "volatility")
        if entry <= 0 or volatility <= 0:
            raise ValueError("invalid market features")
    except (AttributeError, ValueError):
        entry = None
        volatility = None

    exchange = str(getattr(market, "exchange", "")).upper()
    raw_lot_size = getattr(market, "lot_size", 1 if exchange == "NSE" else None)
    try:
        numeric_lot_size = _finite_number(raw_lot_size, "lot size")
        lot_size = int(numeric_lot_size) if numeric_lot_size.is_integer() and numeric_lot_size > 0 else None
    except ValueError:
        lot_size = None

    costs = None
    if isinstance(costs_bps, Mapping) and not (set(_COST_COMPONENTS) - set(costs_bps)):
        try:
            costs = {
                key: _finite_number(costs_bps[key], f"cost {key}")
                for key in _COST_COMPONENTS
            }
            if any(value < 0 for value in costs.values()):
                costs = None
        except ValueError:
            costs = None

    for vote_name, raw_vote in votes.items():
        registered = _STRATEGIES.get(vote_name)
        strategy_id = registered[0] if registered else str(vote_name)
        if not registered:
            reject(strategy_id, "STRATEGY_NOT_REGISTERED")
            continue
        try:
            vote = _finite_number(raw_vote, "vote")
        except ValueError:
            reject(strategy_id, "INVALID_VOTE")
            continue
        if abs(vote) < 0.05:
            reject(strategy_id, "WEAK_SIGNAL")
            continue
        if timestamp is None:
            reject(strategy_id, "DATA_TIMESTAMP_MISSING")
            continue
        if entry is None or volatility is None:
            reject(strategy_id, "MARKET_FEATURES_INVALID")
            continue
        if lot_size is None:
            reject(strategy_id, "LOT_SIZE_MISSING" if raw_lot_size is None else "LOT_SIZE_INVALID")
            continue
        if costs is None:
            reject(strategy_id, "COST_INPUT_MISSING")
            continue

        stop_fraction = max(0.003, min(0.02, 2.0 * volatility))
        direction = 1 if vote > 0 else -1
        stop = entry * (1.0 - direction * stop_fraction)
        target = entry * (1.0 + direction * stop_fraction * 2.0)
        cost_per_unit = {key: entry * value / 10_000.0 for key, value in costs.items()}
        try:
            proposals.append(proposal_from_vote(
                vote,
                strategy_id=registered[0],
                strategy_version=registered[1],
                data_version=data_version,
                validation_version=validation_version,
                market_id=getattr(market, "market_id", ""),
                tradingsymbol=getattr(market, "tradingsymbol", ""),
                exchange=getattr(market, "exchange", ""),
                timeframe=timeframe,
                lot_size=lot_size,
                entry_price=entry,
                stop_price=stop,
                target_price=target,
                confidence=min(0.95, 0.5 + 0.45 * abs(vote)),
                rationale=f"{registered[1]} vote {vote:+.3f}; volatility-scaled estimate is unvalidated",
                features=features,
                signal_timestamp=signal_timestamp,
                data_timestamp=timestamp,
                max_data_age_seconds=max_data_age_seconds,
                estimated_gross_edge=abs(vote) * volatility * entry,
                estimated_costs=cost_per_unit,
            ))
        except (TypeError, ValueError, AttributeError):
            reject(strategy_id, "PROPOSAL_INPUT_INVALID")

    return {"proposals": proposals, "rejections": rejections}


def aggregate_intent_id(
    market_id: str,
    exchange: str,
    direction: int,
    quantity: int,
    proposals,
) -> str:
    """Create one stable broker tag from the proposals backing an order."""
    market = _nonempty(market_id, "market_id")
    venue = _nonempty(exchange, "exchange").upper()
    if venue not in {"NSE", "MCX"}:
        raise ValueError("exchange must be NSE or MCX")
    if type(direction) is not int or direction not in {-1, 1}:
        raise ValueError("direction must be -1 or 1")
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    proposal_ids = sorted({proposal.intent_id for proposal in proposals})
    if not proposal_ids:
        raise ValueError("at least one strategy proposal is required")
    payload = json.dumps(
        [venue, market, direction, quantity, proposal_ids],
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return ("mcx-" if venue == "MCX" else "nse-") + digest
