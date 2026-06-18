"""TD production report — summarize metrics from data/production_metrics.json.

Usage:
    python scripts/production_report.py

Exit codes:
    0 = TD-3 target met (pass rate ≥ 70%)
    1 = Below target
    2 = No metrics found
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from shared.production_metrics import DEFAULT_METRICS_PATH, MetricsRecorder

TARGET_PASS_RATE = 0.70
TARGET_MAX_COST_USD = 5.0
TARGET_MAX_DURATION_MIN = 90


def print_report() -> int:
    metrics_path = DEFAULT_METRICS_PATH
    if not metrics_path.exists():
        print(f"ERROR: No metrics found at {metrics_path}")
        print("Run some TD generations first to populate metrics.")
        return 2

    recorder = MetricsRecorder(metrics_path)
    summary = recorder.summary()

    print("=" * 64)
    print("TD PRODUCTION REPORT")
    print("=" * 64)
    print(f"Metrics file: {metrics_path}")
    print(f"Last updated: {summary.last_updated or '(never)'}")
    print()

    print("OVERALL")
    print("-" * 64)
    print(f"  Total attempts:  {summary.total_attempts}")
    print(f"  Total passed:    {summary.total_passed}")
    print(f"  Pass rate:       {summary.pass_rate:.1%}  "
          f"(target: ≥{TARGET_PASS_RATE:.0%})")
    avg_min = summary.avg_duration_ms / 60000
    print(f"  Avg duration:    {avg_min:.1f} min  "
          f"(target: ≤{TARGET_MAX_DURATION_MIN} min)")
    print(f"  Avg cost:        ${summary.avg_cost_usd:.2f}  "
          f"(target: ≤${TARGET_MAX_COST_USD:.2f})")
    print()

    if summary.per_genre:
        print("PER GENRE")
        print("-" * 64)
        for genre in sorted(summary.per_genre.keys()):
            stats = summary.genre_stats(genre)
            print(f"  {genre}:")
            print(f"    attempts: {stats['attempts']}, "
                  f"passed: {stats['passed']}, "
                  f"pass_rate: {stats['pass_rate']:.1%}")
        print()

    if summary.hard_failure_counts:
        print("HARD FAILURE BREAKDOWN")
        print("-" * 64)
        sorted_fails = sorted(
            summary.hard_failure_counts.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        for check_name, count in sorted_fails:
            pct = count / summary.total_attempts * 100
            print(f"  {check_name:30s}  {count:3d}  ({pct:.0f}%)")
        print()

    print("=" * 64)
    if summary.total_attempts == 0:
        print("NO DATA — run generations to populate metrics")
        return 2
    if summary.pass_rate >= TARGET_PASS_RATE:
        print(f"✓ TD-3 TARGET MET: pass rate {summary.pass_rate:.1%} "
              f"≥ {TARGET_PASS_RATE:.0%}")
        return 0
    print(f"✗ BELOW TARGET: pass rate {summary.pass_rate:.1%} "
          f"< {TARGET_PASS_RATE:.0%}")
    return 1


if __name__ == "__main__":
    sys.exit(print_report())
