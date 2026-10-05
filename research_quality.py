"""Research provenance, freshness, and completeness gates.

All timestamps are UTC epoch seconds. A source is usable only when it is both
available and fresh enough for the configured trading policy.
"""
from dataclasses import dataclass, field
import time


@dataclass
class SourceRecord:
    name: str
    status: str
    fetched_at: float
    age_seconds: float
    evidence_count: int = 0
    warning: str = ""


@dataclass
class ResearchQuality:
    records: dict[str, SourceRecord] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, name, status, fetched_at=None, evidence_count=0, max_age=900):
        now = time.time()
        fetched_at = float(fetched_at or now)
        age = max(0.0, now - fetched_at)
        fresh = age <= max_age
        usable = bool(status) and fresh
        warning = ""
        if not status:
            warning = "unavailable"
        elif not fresh:
            warning = "stale"
        self.records[name] = SourceRecord(
            name, "ok" if usable else ("stale" if status else "unavailable"),
            fetched_at, age, int(evidence_count), warning,
        )
        if not usable:
            self.failures.append(name)
            self.warnings.append(f"research_source_{warning}:{name}")
        return usable

    @property
    def complete(self):
        return not self.failures

    def status(self):
        return {name: rec.status == "ok" for name, rec in self.records.items()}

    def timestamps(self):
        return {name: rec.fetched_at for name, rec in self.records.items()}

    def ages(self):
        return {name: round(rec.age_seconds, 3) for name, rec in self.records.items()}

    def provenance(self):
        return {
            name: {
                "status": rec.status,
                "fetched_at": rec.fetched_at,
                "age_seconds": round(rec.age_seconds, 3),
                "evidence_count": rec.evidence_count,
                "warning": rec.warning,
            }
            for name, rec in self.records.items()
        }
