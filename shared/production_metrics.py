from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

DEFAULT_METRICS_PATH = Path("data/production_metrics.json")


@dataclass
class GenerationRecord:
    timestamp: str
    project_id: str
    genre: str
    theme: str = ""
    passed: bool = False
    hard_failures: list[str] = field(default_factory=list)
    soft_warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    template_used: str = ""


@dataclass
class ProductionMetrics:
    total_attempts: int = 0
    total_passed: int = 0
    hard_failure_counts: dict[str, int] = field(default_factory=dict)
    per_genre: dict[str, dict[str, int]] = field(default_factory=dict)
    total_duration_ms: int = 0
    total_cost_usd: float = 0.0
    last_updated: str = ""

    @property
    def pass_rate(self) -> float:
        return self.total_passed / self.total_attempts if self.total_attempts else 0.0

    @property
    def avg_duration_ms(self) -> float:
        return self.total_duration_ms / self.total_attempts if self.total_attempts else 0.0

    @property
    def avg_cost_usd(self) -> float:
        return self.total_cost_usd / self.total_attempts if self.total_attempts else 0.0

    def genre_stats(self, genre: str) -> dict[str, float]:
        stats = self.per_genre.get(genre, {"attempts": 0, "passed": 0})
        attempts = stats["attempts"]
        passed = stats["passed"]
        return {
            "attempts": attempts,
            "passed": passed,
            "pass_rate": passed / attempts if attempts else 0.0,
        }

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "pass_rate": round(self.pass_rate, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 1),
            "avg_cost_usd": round(self.avg_cost_usd, 4),
        }


class MetricsRecorder:
    def __init__(self, path: Path = DEFAULT_METRICS_PATH) -> None:
        self.path = path
        self._records: list[GenerationRecord] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._records = [GenerationRecord(**r) for r in data.get("records", [])]
            logger.debug(f"Loaded {len(self._records)} production records")
        except (json.JSONDecodeError, OSError, TypeError) as e:
            logger.warning(f"Could not load metrics from {self.path}: {e}")
            self._records = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "records": [asdict(r) for r in self._records],
            "summary": self.summary().to_dict(),
        }
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def record(
        self,
        project_id: str,
        genre: str,
        passed: bool,
        theme: str = "",
        hard_failures: list[str] | None = None,
        soft_warnings: list[str] | None = None,
        duration_ms: int = 0,
        cost_usd: float = 0.0,
        llm_calls: int = 0,
        template_used: str = "",
    ) -> GenerationRecord:
        record = GenerationRecord(
            timestamp=datetime.now(UTC).isoformat(),
            project_id=project_id,
            genre=genre,
            theme=theme,
            passed=passed,
            hard_failures=hard_failures or [],
            soft_warnings=soft_warnings or [],
            duration_ms=duration_ms,
            cost_usd=cost_usd,
            llm_calls=llm_calls,
            template_used=template_used,
        )
        self._records.append(record)
        self._save()
        return record

    def summary(self) -> ProductionMetrics:
        metrics = ProductionMetrics()
        metrics.total_attempts = len(self._records)

        for r in self._records:
            if r.passed:
                metrics.total_passed += 1
            metrics.total_duration_ms += r.duration_ms
            metrics.total_cost_usd += r.cost_usd

            for fail in r.hard_failures:
                metrics.hard_failure_counts[fail] = (
                    metrics.hard_failure_counts.get(fail, 0) + 1
                )

            genre_stats = metrics.per_genre.setdefault(
                r.genre, {"attempts": 0, "passed": 0}
            )
            genre_stats["attempts"] += 1
            if r.passed:
                genre_stats["passed"] += 1

        metrics.last_updated = datetime.now(UTC).isoformat()
        return metrics

    def clear(self) -> None:
        self._records = []
        if self.path.exists():
            self.path.unlink()


def get_recorder(path: Path | None = None) -> MetricsRecorder:
    return MetricsRecorder(path or DEFAULT_METRICS_PATH)
