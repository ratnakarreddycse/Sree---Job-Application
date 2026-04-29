import json
from pathlib import Path

from job_applications.ui import (
    UiConfig,
    _find_latest_manifest,
    _looks_like_listing_url,
    _pick_best_link_from_html,
    _safe_open_path,
    build_pipeline_command,
    load_ui_config,
)


def test_load_ui_config_uses_defaults_when_missing(tmp_path: Path) -> None:
    config = load_ui_config(tmp_path / "missing.json")

    assert config.input_path is None
    assert config.daily_output_root == "outputs"
    assert "linkedin" in config.portals


def test_load_ui_config_reads_portals(tmp_path: Path) -> None:
    config_path = tmp_path / "portal_config.json"
    config_path.write_text(
        """
{
  "input_path": "jobs.json",
  "daily_output_root": "daily_outputs",
  "top": 10,
  "portals": {
    "linkedin": ["https://linkedin.example/search"],
    "indeed": ["https://indeed.example/search"]
  }
}
        """.strip(),
        encoding="utf-8",
    )

    config = load_ui_config(config_path)

    assert config.input_path == "jobs.json"
    assert config.daily_output_root == "daily_outputs"
    assert config.top == 10
    assert config.portals["linkedin"] == ["https://linkedin.example/search"]


def test_build_pipeline_command_uses_config() -> None:
    config = UiConfig(
        input_path="jobs.json",
        daily_output_root="outputs",
        top=30,
        portals={"linkedin": []},
        base_resume="base_resume.json",
        rss_urls=["https://example.com/rss"],
    )

    command = build_pipeline_command(config)

    assert "job_applications.cli" in command
    assert "--input" in command
    assert "jobs.json" in command
    assert "--top" in command
    assert "30" in command
    assert "--base-resume" in command
    assert "base_resume.json" in command
    assert "--rss-url" in command
    assert "https://example.com/rss" in command


# ---------------------------------------------------------------------------
# _find_latest_manifest
# ---------------------------------------------------------------------------

def test_find_latest_manifest_returns_none_when_root_missing(tmp_path: Path) -> None:
    result = _find_latest_manifest(str(tmp_path / "nonexistent"))
    assert result is None


def test_find_latest_manifest_picks_most_recent(tmp_path: Path) -> None:
    for date_str, jobs in [("2026-04-20", [{"rank": 1}]), ("2026-04-25", [{"rank": 2}])]:
        d = tmp_path / date_str
        d.mkdir()
        (d / "manifest.json").write_text(
            json.dumps({"generated_on": date_str, "jobs": jobs}), encoding="utf-8"
        )

    result = _find_latest_manifest(str(tmp_path))
    assert result is not None
    assert result["generated_on"] == "2026-04-25"
    assert result["jobs"][0]["rank"] == 2


def test_find_latest_manifest_skips_dir_without_manifest(tmp_path: Path) -> None:
    (tmp_path / "2026-04-24").mkdir()  # no manifest.json
    d = tmp_path / "2026-04-23"
    d.mkdir()
    (d / "manifest.json").write_text(
        json.dumps({"generated_on": "2026-04-23", "jobs": []}), encoding="utf-8"
    )

    result = _find_latest_manifest(str(tmp_path))
    assert result is not None
    assert result["generated_on"] == "2026-04-23"


# ---------------------------------------------------------------------------
# _safe_open_path
# ---------------------------------------------------------------------------

def test_safe_open_path_rejects_path_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    outside = tmp_path / "other" / "secret.md"
    ok, msg = _safe_open_path(str(outside), str(root))
    assert ok is False
    assert "outside" in msg.lower() or "not found" in msg.lower() or "allowed" in msg.lower()


def test_safe_open_path_rejects_disallowed_extension(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    bad_file = root / "script.sh"
    bad_file.write_text("rm -rf /", encoding="utf-8")
    ok, msg = _safe_open_path(str(bad_file), str(root))
    assert ok is False
    assert "type" in msg.lower() or "not allowed" in msg.lower()


def test_safe_open_path_rejects_missing_file(tmp_path: Path) -> None:
    root = tmp_path / "outputs"
    root.mkdir()
    missing = root / "resume.md"
    ok, msg = _safe_open_path(str(missing), str(root))
    assert ok is False
    assert "not found" in msg.lower()


def test_looks_like_listing_url_identifies_generic_career_pages() -> None:
    # Current career listing pages (working URLs as of 2026-04)
    assert _looks_like_listing_url("https://www.databricks.com/company/careers/open-positions") is True
    assert _looks_like_listing_url("https://careers.snowflake.com/us/en/search-results") is True
    assert _looks_like_listing_url("https://stripe.com/jobs/search") is True
    assert _looks_like_listing_url("https://careers.confluent.io/jobs") is True

    # Search-query listing pages
    assert _looks_like_listing_url("https://stripe.com/jobs/search?query=data+engineer") is True
    assert _looks_like_listing_url("https://careers.confluent.io/jobs/?search=analytics+engineer") is True

    # Legacy Greenhouse / Lever board root pages are still listing pages
    assert _looks_like_listing_url("https://boards.greenhouse.io/databricks") is True
    assert _looks_like_listing_url("https://boards.greenhouse.io/confluent") is True
    assert _looks_like_listing_url("https://job-boards.greenhouse.io/confluent") is True
    assert _looks_like_listing_url("https://jobs.lever.co/stripe") is True

    # Workday job sites are listing pages
    assert _looks_like_listing_url("https://snowflake.wd1.myworkdayjobs.com/en-US/SnowflakeCareer") is True

    # Direct posting URLs with long numeric IDs are NOT listing pages
    assert _looks_like_listing_url("https://boards.greenhouse.io/databricks/jobs/1234567") is False
    assert _looks_like_listing_url("https://www.databricks.com/company/careers/engineering/senior-data-engineer-8229672002") is False
    assert _looks_like_listing_url("https://careers.snowflake.com/us/en/job/SNCOUS4414B8D62C59/Senior-Solution-Engineer") is False
    assert _looks_like_listing_url("https://jobicy.com/jobs/142241-senior-data-engineer") is False
    assert _looks_like_listing_url("https://weworkremotely.com/remote-jobs/ataccama-senior-back-end-engineer") is False


def test_pick_best_link_from_html_prefers_role_matching_direct_link() -> None:
    listing_url = "https://example.com/company/careers/open-positions"
    html = """
    <html><body>
      <a href="/company/careers/open-positions">Open positions</a>
      <a href="/jobs/11111">Data Analyst</a>
      <a href="/jobs/98765">Senior Data Engineer</a>
    </body></html>
    """

    best = _pick_best_link_from_html(
        listing_url,
        html,
        role="Senior Data Engineer",
        company="Databricks",
    )

    assert best == "https://example.com/jobs/98765"
