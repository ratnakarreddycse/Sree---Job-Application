from datetime import date
from types import SimpleNamespace

from job_applications.cli import _resolve_daily_paths


def test_resolve_daily_paths_uses_defaults_when_daily_run_enabled() -> None:
    args = SimpleNamespace(
        daily_run=True,
        daily_output_root="outputs",
        output=None,
        export_csv=None,
        drafts_dir=None,
    )

    output_path, csv_path, drafts_dir = _resolve_daily_paths(args, date(2026, 4, 25))

    assert str(output_path) == "outputs/2026-04-25/summary.json"
    assert str(csv_path) == "outputs/2026-04-25/top_jobs.csv"
    assert str(drafts_dir) == "outputs/2026-04-25/drafts"


def test_resolve_daily_paths_uses_explicit_values_when_provided() -> None:
    args = SimpleNamespace(
        daily_run=True,
        daily_output_root="outputs",
        output="custom/summary.json",
        export_csv="custom/top.csv",
        drafts_dir="custom/drafts",
    )

    output_path, csv_path, drafts_dir = _resolve_daily_paths(args, date(2026, 4, 25))

    assert str(output_path) == "custom/summary.json"
    assert str(csv_path) == "custom/top.csv"
    assert str(drafts_dir) == "custom/drafts"