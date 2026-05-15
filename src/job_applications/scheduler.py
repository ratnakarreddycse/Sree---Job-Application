from __future__ import annotations

import plistlib
import shutil
import subprocess
from pathlib import Path


def build_daily_program_args(
    python_executable: str,
    input_path: str | None,
    daily_output_root: str,
    top: int,
    rss_urls: list[str],
    rss_limit: int,
    rss_status: str,
    no_dedupe: bool,
    require_visa_support: bool,
) -> list[str]:
    args = [
        python_executable,
        "-m",
        "job_applications.cli",
        "--daily-run",
        "--daily-output-root",
        daily_output_root,
        "--top",
        str(top),
        "--rss-limit",
        str(rss_limit),
        "--rss-status",
        rss_status,
    ]

    if input_path:
        args.extend(["--input", input_path])

    for url in rss_urls:
        args.extend(["--rss-url", url])

    if no_dedupe:
        args.append("--no-dedupe")

    if not require_visa_support:
        args.append("--no-require-visa-support")

    return args


def build_launchd_plist(
    label: str,
    program_arguments: list[str],
    working_directory: str,
    hour: int,
    minute: int,
    stdout_path: str,
    stderr_path: str,
) -> bytes:
    payload = {
        "Label": label,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": working_directory,
        "RunAtLoad": True,
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "StandardOutPath": stdout_path,
        "StandardErrorPath": stderr_path,
    }
    return plistlib.dumps(payload, sort_keys=False)


def write_launchd_plist(output_path: Path, plist_content: bytes) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(plist_content)


def install_launchd_agent(
    source_plist_path: Path,
    label: str,
    agent_dir: Path,
    run_launchctl: bool = True,
) -> Path:
    agent_dir.mkdir(parents=True, exist_ok=True)
    target_path = agent_dir / f"{label}.plist"
    shutil.copy2(source_plist_path, target_path)

    if run_launchctl:
        subprocess.run(
            ["launchctl", "unload", str(target_path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(["launchctl", "load", str(target_path)], check=True)

    return target_path


def uninstall_launchd_agent(
    label: str,
    agent_dir: Path,
    run_launchctl: bool = True,
) -> Path:
    target_path = agent_dir / f"{label}.plist"

    if run_launchctl and target_path.exists():
        subprocess.run(
            ["launchctl", "unload", str(target_path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    if target_path.exists():
        target_path.unlink()

    return target_path


def get_launchd_agent_status(label: str, agent_dir: Path) -> dict[str, object]:
    plist_path = agent_dir / f"{label}.plist"
    installed = plist_path.exists()
    loaded = False
    launchctl_error = ""

    try:
        result = subprocess.run(
            ["launchctl", "list", label],
            check=False,
            capture_output=True,
            text=True,
        )
        loaded = result.returncode == 0
        if result.returncode != 0:
            launchctl_error = result.stderr.strip() or result.stdout.strip()
    except FileNotFoundError:
        launchctl_error = "launchctl not found"

    return {
        "label": label,
        "plist_path": str(plist_path),
        "installed": installed,
        "loaded": loaded,
        "launchctl_error": launchctl_error,
    }