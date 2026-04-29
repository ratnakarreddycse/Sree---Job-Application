from pathlib import Path

from job_applications.health import build_outputs_health_report


def test_build_outputs_health_report_no_runs(tmp_path: Path) -> None:
    report = build_outputs_health_report(tmp_path, freshness_days=1)

    assert report["latest_run_date"] is None
    assert report["fresh"] is False
    assert report["summary_exists"] is False


def test_build_outputs_health_report_latest_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "2026-04-25"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "summary.json").write_text("{}", encoding="utf-8")
    (run_dir / "top_jobs.csv").write_text("company\n", encoding="utf-8")
    drafts_dir = run_dir / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    (drafts_dir / "01.md").write_text("draft", encoding="utf-8")

    report = build_outputs_health_report(tmp_path, freshness_days=10000)

    assert report["latest_run_date"] == "2026-04-25"
    assert report["summary_exists"] is True
    assert report["top_jobs_exists"] is True
    assert report["drafts_count"] == 1
    assert report["fresh"] is True
