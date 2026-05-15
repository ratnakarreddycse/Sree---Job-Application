from __future__ import annotations

from datetime import date
from pathlib import Path


def build_outputs_health_report(output_root: Path, freshness_days: int = 1) -> dict[str, object]:
    latest_dir = _latest_dated_dir(output_root)
    if latest_dir is None:
        return {
            "output_root": str(output_root),
            "latest_run_date": None,
            "summary_exists": False,
            "top_jobs_exists": False,
            "drafts_count": 0,
            "age_days": None,
            "fresh": False,
            "freshness_days": freshness_days,
        }

    run_date = date.fromisoformat(latest_dir.name)
    age_days = (date.today() - run_date).days
    summary_exists = (latest_dir / "summary.json").exists()
    top_jobs_exists = (latest_dir / "top_jobs.csv").exists()
    drafts_dir = latest_dir / "drafts"
    drafts_count = len(list(drafts_dir.glob("*.md"))) if drafts_dir.exists() else 0

    return {
        "output_root": str(output_root),
        "latest_run_date": run_date.isoformat(),
        "summary_exists": summary_exists,
        "top_jobs_exists": top_jobs_exists,
        "drafts_count": drafts_count,
        "age_days": age_days,
        "fresh": age_days <= freshness_days,
        "freshness_days": freshness_days,
    }


def _latest_dated_dir(output_root: Path) -> Path | None:
    if not output_root.exists():
        return None

    dated_dirs: list[Path] = []
    for child in output_root.iterdir():
        if not child.is_dir():
            continue
        try:
            date.fromisoformat(child.name)
        except ValueError:
            continue
        dated_dirs.append(child)

    if not dated_dirs:
        return None

    return max(dated_dirs, key=lambda item: item.name)