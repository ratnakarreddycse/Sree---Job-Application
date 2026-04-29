import plistlib
from pathlib import Path
from unittest.mock import patch

from job_applications.scheduler import (
    build_daily_program_args,
    build_launchd_plist,
    get_launchd_agent_status,
    install_launchd_agent,
    uninstall_launchd_agent,
)


def test_build_daily_program_args_includes_input_and_rss() -> None:
    args = build_daily_program_args(
        python_executable="python3",
        input_path="applications.json",
        daily_output_root="outputs",
        top=20,
        rss_urls=["https://example.com/jobs.rss"],
        rss_limit=10,
        rss_status="new",
        no_dedupe=False,
        require_visa_support=True,
    )

    assert "--input" in args
    assert "applications.json" in args
    assert "--rss-url" in args
    assert "https://example.com/jobs.rss" in args


def test_build_launchd_plist_contains_calendar_interval() -> None:
    plist_bytes = build_launchd_plist(
        label="com.jobapplications.daily",
        program_arguments=["python3", "-m", "job_applications.cli"],
        working_directory="/tmp",
        hour=8,
        minute=15,
        stdout_path="logs/out.log",
        stderr_path="logs/err.log",
    )

    parsed = plistlib.loads(plist_bytes)

    assert parsed["Label"] == "com.jobapplications.daily"
    assert parsed["StartCalendarInterval"] == {"Hour": 8, "Minute": 15}
    assert parsed["ProgramArguments"][0] == "python3"


def test_install_launchd_agent_copies_plist_without_launchctl(tmp_path: Path) -> None:
    source = tmp_path / "source.plist"
    source.write_text("<plist></plist>", encoding="utf-8")
    target = install_launchd_agent(
        source_plist_path=source,
        label="com.jobapplications.daily",
        agent_dir=tmp_path / "agents",
        run_launchctl=False,
    )

    assert target.exists()
    assert target.read_text(encoding="utf-8") == "<plist></plist>"


def test_uninstall_launchd_agent_removes_plist_without_launchctl(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    target = agents_dir / "com.jobapplications.daily.plist"
    target.write_text("<plist></plist>", encoding="utf-8")

    removed_path = uninstall_launchd_agent(
        label="com.jobapplications.daily",
        agent_dir=agents_dir,
        run_launchctl=False,
    )

    assert removed_path == target
    assert not target.exists()


def test_get_launchd_agent_status_when_installed_and_loaded(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agents_dir / "com.jobapplications.daily.plist"
    plist_path.write_text("<plist></plist>", encoding="utf-8")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stderr = ""
        mock_run.return_value.stdout = ""
        status = get_launchd_agent_status("com.jobapplications.daily", agents_dir)

    assert status["installed"] is True
    assert status["loaded"] is True
    assert status["plist_path"] == str(plist_path)
