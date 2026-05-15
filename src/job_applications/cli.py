from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from datetime import date
from os.path import expanduser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from job_applications.drafting import write_application_drafts
from job_applications.health import build_outputs_health_report
from job_applications.ingestion import (
    dedupe_records,
    fetch_ats_records,
    fetch_jsearch_records,
    fetch_rss_records,
    fetch_smartrecruiters_records,
    fetch_workday_records,
    load_records_from_file,
    merge_duplicate_records,
)
from job_applications.pipeline import CandidateProfile, default_profile, run_pipeline
from job_applications.scheduler import (
    build_daily_program_args,
    build_launchd_plist,
    get_launchd_agent_status,
    install_launchd_agent,
    uninstall_launchd_agent,
    write_launchd_plist,
)


def _split_csv_values(raw_value: str) -> list[str]:
    return [item.strip().lower() for item in raw_value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the job application pipeline")
    parser.add_argument("--input", help="Path to an input file (.json or .csv) of applications")
    parser.add_argument(
        "--rss-url",
        action="append",
        default=[],
        help="RSS feed URL for jobs (can be provided multiple times)",
    )
    parser.add_argument("--rss-limit", type=int, default=25, help="Max items to ingest per RSS feed")
    parser.add_argument("--rss-status", default="new", help="Default status for RSS-ingested records")
    parser.add_argument(
        "--portal-config",
        default="portal_config.json",
        help="Path to portal_config.json containing ats_boards configuration",
    )
    parser.add_argument("--output", help="Optional JSON output path for the full summary")
    parser.add_argument("--export-csv", help="Optional CSV output path for top recommendations")
    parser.add_argument("--drafts-dir", help="Optional directory to write per-job markdown drafts")
    parser.add_argument(
        "--daily-run",
        action="store_true",
        help="Write outputs into a date-stamped folder for daily execution",
    )
    parser.add_argument(
        "--daily-output-root",
        default="outputs",
        help="Root folder used by --daily-run",
    )
    parser.add_argument(
        "--write-macos-launchd",
        action="store_true",
        help="Generate a launchd plist for daily automated execution on macOS",
    )
    parser.add_argument(
        "--launchd-label",
        default="com.jobapplications.daily",
        help="launchd label used when generating the plist",
    )
    parser.add_argument(
        "--launchd-hour",
        type=int,
        default=8,
        help="Hour (0-23) for daily launchd execution",
    )
    parser.add_argument(
        "--launchd-minute",
        type=int,
        default=0,
        help="Minute (0-59) for daily launchd execution",
    )
    parser.add_argument(
        "--launchd-plist-path",
        default="scheduler/com.jobapplications.daily.plist",
        help="Path to write the generated launchd plist",
    )
    parser.add_argument(
        "--install-macos-launchd",
        action="store_true",
        help="Install generated plist into ~/Library/LaunchAgents and load it",
    )
    parser.add_argument(
        "--uninstall-macos-launchd",
        action="store_true",
        help="Unload and remove plist from ~/Library/LaunchAgents",
    )
    parser.add_argument(
        "--launchd-agent-dir",
        default="~/Library/LaunchAgents",
        help="Directory where the launchd agent plist is installed",
    )
    parser.add_argument(
        "--status-macos-launchd",
        action="store_true",
        help="Show installed and loaded state of the launchd agent",
    )
    parser.add_argument(
        "--health-report",
        action="store_true",
        help="Show combined scheduler status and daily output freshness",
    )
    parser.add_argument(
        "--freshness-days",
        type=int,
        default=1,
        help="How many days old output can be and still be considered fresh",
    )
    parser.add_argument("--top", type=int, default=0, help="Number of top recommendations to keep (0 = all)")
    parser.add_argument(
        "--no-dedupe",
        action="store_true",
        help="Disable deduplication by company+role+notes",
    )
    parser.add_argument(
        "--target-titles",
        default=",".join(default_profile().target_titles),
        help="Comma-separated target titles",
    )
    parser.add_argument(
        "--required-keywords",
        default=",".join(default_profile().required_keywords),
        help="Comma-separated required keywords",
    )
    parser.add_argument(
        "--preferred-keywords",
        default=",".join(default_profile().preferred_keywords),
        help="Comma-separated preferred keywords",
    )
    parser.add_argument(
        "--preferred-locations",
        default=",".join(default_profile().preferred_locations),
        help="Comma-separated preferred location signals",
    )
    parser.add_argument(
        "--require-visa-support",
        action="store_true",
        default=True,
        help="Require positive visa compatibility and reject negative visa-signal roles",
    )
    parser.add_argument(
        "--no-require-visa-support",
        action="store_false",
        dest="require_visa_support",
        help="Disable visa support checks",
    )
    parser.add_argument(
        "--base-resume",
        default=None,
        help="Path to base_resume.json; enables per-job tailored resume generation alongside drafts",
    )
    return parser


def _to_serializable(summary: object) -> dict[str, object]:
    return summary.__dict__


def _extract_apply_url(notes: str) -> str | None:
    """Extract a job posting URL from notes when present.

    Expected patterns include:
    - "Link: https://..."
    - any embedded http/https URL
    """
    if not notes:
        return None

    explicit = re.search(r"\bLink:\s*(https?://\S+)", notes, flags=re.IGNORECASE)
    if explicit:
        return explicit.group(1).rstrip(").,;\"'")

    generic = re.search(r"\bhttps?://\S+", notes)
    if generic:
        return generic.group(0).rstrip(").,;\"'")

    return None


def _score_apply_url_specificity(url: str) -> int:
    """Higher score means more likely to be a direct job posting URL."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return -100

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return -100

    path = parsed.path.lower().rstrip("/")
    query = parse_qs(parsed.query.lower())
    score = 0

    # Penalize generic listing/search endpoints.
    listing_paths = {
        "",
        "/",
        "/careers",
        "/jobs",
        "/company/careers",
        "/company/careers/open-positions",
        "/search-results",
    }
    if path in listing_paths:
        score -= 6

    if any(token in path for token in ["search", "open-positions", "open_positions", "job-search"]):
        score -= 4

    if any(key in query for key in ["search", "query", "keywords", "department", "location"]):
        score -= 3

    # Reward paths that look like concrete job postings.
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) >= 2:
        score += 2

    if any(token in path for token in ["/job/", "/jobs/", "/position/", "/positions/"]):
        score += 3

    if re.search(r"\d", path):
        score += 1

    # Reward ATS job ID query parameters (Greenhouse gh_jid, Workday jobId, etc.)
    if any(key in query for key in ["gh_jid", "job_id", "jobid", "jid"]):
        score += 4

    # Reward numeric job IDs in the query string (catches gh_jid=8486738002 etc.)
    if re.search(r"\d{5,}", parsed.query):
        score += 3

    # Reward UUID patterns in the path (Ashby, Lever use /slug/UUID format)
    if re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", path):
        score += 4

    return score


def _build_best_apply_url_map(records: list[dict[str, str]]) -> dict[tuple[str, str], str]:
    """Choose the best apply URL per (company, role) across all ingested records."""
    best: dict[tuple[str, str], tuple[int, int, str]] = {}

    for idx, record in enumerate(records):
        company = record.get("company", "").strip()
        role = record.get("role", "").strip()
        if not company or not role:
            continue

        # Prefer the dedicated apply_url field; fall back to extracting from notes.
        url = record.get("apply_url", "").strip() or _extract_apply_url(record.get("notes", "") or "")
        if not url:
            continue

        key = (company.lower(), role.lower())
        candidate = (_score_apply_url_specificity(url), idx, url)
        current = best.get(key)
        if current is None or candidate[0] > current[0]:
            best[key] = candidate

    return {key: value[2] for key, value in best.items()}


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = ["company", "role", "status", "score", "action", "apply_url", "reasons", "notes"]
    with path.open("w", newline="", encoding="utf-8") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            normalized_row = dict(row)
            normalized_row["reasons"] = "; ".join(str(item) for item in row.get("reasons", []))
            writer.writerow(normalized_row)


def _resolve_daily_paths(args: argparse.Namespace, run_date: date) -> tuple[Path | None, Path | None, Path | None]:
    if not args.daily_run:
        output_path = Path(args.output) if args.output else None
        csv_path = Path(args.export_csv) if args.export_csv else None
        drafts_dir = Path(args.drafts_dir) if args.drafts_dir else None
        return output_path, csv_path, drafts_dir

    daily_dir = Path(args.daily_output_root) / run_date.isoformat()
    output_path = Path(args.output) if args.output else daily_dir / "summary.json"
    csv_path = Path(args.export_csv) if args.export_csv else daily_dir / "top_jobs.csv"
    drafts_dir = Path(args.drafts_dir) if args.drafts_dir else daily_dir / "drafts"
    return output_path, csv_path, drafts_dir


def main() -> None:
    args = build_parser().parse_args()
    if args.health_report:
        agent_dir = Path(expanduser(args.launchd_agent_dir))
        health_payload = {
            "scheduler": get_launchd_agent_status(args.launchd_label, agent_dir),
            "outputs": build_outputs_health_report(Path(args.daily_output_root), freshness_days=args.freshness_days),
        }
        print(json.dumps(health_payload, indent=2, sort_keys=True))
        return

    if args.status_macos_launchd:
        agent_dir = Path(expanduser(args.launchd_agent_dir))
        status = get_launchd_agent_status(args.launchd_label, agent_dir)
        print(json.dumps(status, indent=2, sort_keys=True))
        return

    if args.uninstall_macos_launchd:
        agent_dir = Path(expanduser(args.launchd_agent_dir))
        removed_path = uninstall_launchd_agent(args.launchd_label, agent_dir)
        print(json.dumps({"path": str(removed_path), "uninstalled": True}, indent=2, sort_keys=True))
        return

    if not args.input and not args.rss_url and not args.portal_config:
        raise SystemExit("Provide at least one source: --input, --rss-url, or --portal-config")
    if args.launchd_hour < 0 or args.launchd_hour > 23:
        raise SystemExit("--launchd-hour must be in the range 0..23")
    if args.launchd_minute < 0 or args.launchd_minute > 59:
        raise SystemExit("--launchd-minute must be in the range 0..59")

    records: list[dict[str, str]] = []
    seed_records: list[dict[str, str]] = []
    if args.input:
        input_path = Path(args.input)
        seed_records = load_records_from_file(input_path)
        records.extend(seed_records)

    if args.rss_url:
        records.extend(fetch_rss_records(args.rss_url, limit_per_feed=args.rss_limit, default_status=args.rss_status))

    if args.portal_config:
        portal_cfg_path = Path(args.portal_config)
        if portal_cfg_path.exists():
            try:
                portal_cfg = json.loads(portal_cfg_path.read_text(encoding="utf-8"))
                ats_boards = portal_cfg.get("ats_boards", [])
                if ats_boards:
                    ats_records = fetch_ats_records(ats_boards, default_status=args.rss_status)
                    # Enrich ATS records with notes from matching seed records (same company)
                    # so they score well on keyword/visa matching instead of just "Source: Greenhouse/..."
                    seed_notes_by_company: dict[str, str] = {}
                    for sr in seed_records:
                        cname = sr.get("company", "").strip().lower()
                        notes = sr.get("notes", "").strip()
                        if cname and notes:
                            seed_notes_by_company[cname] = notes
                    for ar in ats_records:
                        cname = ar.get("company", "").strip().lower()
                        if cname in seed_notes_by_company:
                            ar["notes"] = seed_notes_by_company[cname] + " " + ar["notes"]
                    records.extend(ats_records)

                # --- Workday boards (free, no auth) ---
                workday_boards = portal_cfg.get("workday_boards", [])
                if workday_boards:
                    records.extend(
                        fetch_workday_records(workday_boards, default_status=args.rss_status)
                    )

                # --- SmartRecruiters boards (free, no auth) ---
                sr_boards = portal_cfg.get("smartrecruiters_boards", [])
                if sr_boards:
                    records.extend(
                        fetch_smartrecruiters_records(sr_boards, default_status=args.rss_status)
                    )

                # --- JSearch API (LinkedIn / Indeed / Glassdoor / ZipRecruiter / Dice) ---
                jsearch_queries = portal_cfg.get("jsearch_queries", [])
                if jsearch_queries:
                    jsearch_api_key = os.environ.get("JSEARCH_API_KEY", "")
                    if jsearch_api_key:
                        records.extend(
                            fetch_jsearch_records(
                                jsearch_queries,
                                jsearch_api_key,
                                default_status=args.rss_status,
                            )
                        )
                    else:
                        print(
                            "[cli] JSEARCH_API_KEY not set; skipping JSearch "
                            "(covers LinkedIn/Glassdoor/ZipRecruiter/Dice — set the env var for full coverage)",
                            file=sys.stderr,
                        )

            except (json.JSONDecodeError, OSError) as exc:
                print(f"[cli] warning: could not read portal config {args.portal_config!r}: {exc}", file=sys.stderr)

    if not args.no_dedupe:
        records = merge_duplicate_records(records)
        records = dedupe_records(records)

    # Apply role blocklist — remove records whose title contains any blocked pattern.
    blocked_role_patterns: list[str] = []
    if args.portal_config:
        portal_cfg_path = Path(args.portal_config)
        if portal_cfg_path.exists():
            try:
                _pcfg = json.loads(portal_cfg_path.read_text(encoding="utf-8"))
                blocked_role_patterns = [p.lower() for p in _pcfg.get("blocked_role_patterns", []) if str(p).strip()]
            except (json.JSONDecodeError, OSError):
                pass

    if blocked_role_patterns:
        before = len(records)
        records = [
            r for r in records
            if not any(pat in r.get("role", "").lower() for pat in blocked_role_patterns)
        ]
        filtered = before - len(records)
        if filtered:
            print(f"[cli] role filter: removed {filtered} records matching blocked patterns", file=sys.stderr)

    best_apply_urls = _build_best_apply_url_map(records)

    # Build a company -> [(role, url, location)] map of direct posting URLs from ATS/RSS records.
    # Used to upgrade seed records that have listing-page URLs, matching by title overlap.
    _ROLE_STOP_WORDS = {"senior", "staff", "principal", "lead", "jr", "junior", "associate",
                        "the", "a", "an", "of", "and", "or", "in", "at", "for", "to", "ii", "iii"}
    ats_direct_by_company: dict[str, list[tuple[str, str, str]]] = {}
    for rec_item in records:
        url = rec_item.get("apply_url", "").strip()
        if not url or _score_apply_url_specificity(url) <= 0:
            continue
        cname = rec_item.get("company", "").strip().lower()
        role = rec_item.get("role", "").strip()
        location = rec_item.get("location", "").strip()
        if not cname:
            continue
        ats_direct_by_company.setdefault(cname, []).append((role, url, location))

    _US_LOCATION_TERMS = {"united states", "remote", "california", "new york", "washington",
                          "texas", "illinois", "colorado", "massachusetts", "georgia", "virginia",
                          "north carolina", "new jersey", "florida", "seattle", "san francisco",
                          "mountain view", "bellevue", "new york city", "chicago", "austin", "denver"}

    def _best_direct_url_for_role(company: str, seed_role: str) -> str | None:
        """Return the direct ATS URL whose role best matches seed_role by word overlap.
        Prefers US/Remote locations over international ones to avoid wrong-country matches."""
        candidates = ats_direct_by_company.get(company.strip().lower(), [])
        if not candidates:
            return None
        seed_words = {w.lower() for w in re.split(r"[\s/,()-]+", seed_role) if w.lower() not in _ROLE_STOP_WORDS and len(w) > 2}
        best_url, best_overlap, best_loc_score = None, -1, -1
        for role, url, location in candidates:
            role_words = {w.lower() for w in re.split(r"[\s/,()-]+", role) if w.lower() not in _ROLE_STOP_WORDS and len(w) > 2}
            overlap = len(seed_words & role_words)
            url_score = _score_apply_url_specificity(url)
            loc_lower = location.lower()
            loc_score = 1 if any(term in loc_lower for term in _US_LOCATION_TERMS) else 0
            # Rank by: overlap first, then US location preference, then URL specificity
            if (overlap, loc_score, url_score) > (best_overlap, best_loc_score, _score_apply_url_specificity(best_url or "")):
                best_url, best_overlap, best_loc_score = url, overlap, loc_score
        # Only upgrade if there are at least 2 meaningful words in common (avoids "engineer" alone matching any engineering role)
        return best_url if best_overlap >= 2 else None

    profile = CandidateProfile(
        target_titles=_split_csv_values(args.target_titles),
        required_keywords=_split_csv_values(args.required_keywords),
        preferred_keywords=_split_csv_values(args.preferred_keywords),
        preferred_locations=_split_csv_values(args.preferred_locations),
        require_visa_support=args.require_visa_support,
    )
    summary = run_pipeline(records, profile=profile, top_k=args.top)
    payload = _to_serializable(summary)
    payload["source_records"] = len(records)
    run_date = date.today()
    output_path, csv_path, drafts_dir = _resolve_daily_paths(args, run_date)

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    if csv_path:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        _write_csv(csv_path, summary.top_recommendations)

    if drafts_dir:
        actionable = [
            item
            for item in summary.top_recommendations
            if str(item.get("action", "")) in {"apply_now", "review_fast"}
        ]
        written = write_application_drafts(actionable, drafts_dir, generated_on=run_date)
        payload["draft_files_written"] = len(written)

        # Drafts map: company+role → draft path (for actionable jobs only)
        draft_map: dict[tuple[str, str], str] = {}
        for rec, draft_path in zip(actionable, written):
            key = (str(rec.get("company", "")), str(rec.get("role", "")))
            draft_map[key] = str(draft_path.resolve())

        # Build manifest — ALL top_recommendations so UI table is never empty
        manifest_jobs: list[dict[str, object]] = []
        for idx, rec in enumerate(summary.top_recommendations, start=1):
            key = (str(rec.get("company", "")), str(rec.get("role", "")))
            normalized_key = (key[0].strip().lower(), key[1].strip().lower())
            # Direct field first, then best-URL map (covers RSS records), then notes extraction.
            apply_url = (
                str(rec.get("apply_url") or "")
                or best_apply_urls.get(normalized_key)
                or _extract_apply_url(str(rec.get("notes", "")))
            ) or None
            # Upgrade listing-page URLs to the best matching direct posting URL (by title overlap).
            if apply_url and _score_apply_url_specificity(apply_url) <= 0:
                role_direct = _best_direct_url_for_role(key[0], key[1])
                if role_direct:
                    apply_url = role_direct
            manifest_jobs.append({
                "rank": idx,
                "company": str(rec.get("company", "")),
                "role": str(rec.get("role", "")),
                "score": rec.get("score", 0),
                "action": str(rec.get("action", "")),
                "apply_url": apply_url,
                "draft_file": draft_map.get(key),
                "resume_file": None,
                "keyword_match_score": None,
            })

        if args.base_resume:
            from job_applications.resume_tailor import load_base_resume, tailor_resume, write_tailored_resume
            from job_applications.drafting import _slugify  # type: ignore[attr-defined]
            base_resume_obj = load_base_resume(args.base_resume)

            # Persistent resume store: resumes/<YYYY-MM-DD>/ — flushed daily
            resumes_root = Path(args.daily_output_root).parent / "resumes"
            resumes_daily_dir = resumes_root / run_date.isoformat()
            resumes_daily_dir.mkdir(parents=True, exist_ok=True)
            # Delete previous date dirs so only today's resumes are kept
            for old_dir in resumes_root.iterdir():
                if old_dir.is_dir() and old_dir.name != run_date.isoformat():
                    import shutil
                    shutil.rmtree(old_dir, ignore_errors=True)

            # Load existing index (so we can merge/update)
            index_path = resumes_root / "index.json"
            resume_index: dict[str, object] = {"generated_on": run_date.isoformat(), "resumes": {}}

            tailored_count = 0
            for manifest_job, rec in zip(manifest_jobs, summary.top_recommendations):
                if str(rec.get("action", "")) not in {"apply_now", "review_fast"}:
                    continue
                jd_text = str(rec.get("notes", ""))
                if not jd_text:
                    continue
                role = str(rec.get("role", "role"))
                company = str(rec.get("company", "company"))
                tailored = tailor_resume(base_resume_obj, jd_text, role, company)
                slug = _slugify(f"{company}_{role}")

                # Write to daily drafts dir (for UI/drafts view)
                resume_path = Path(drafts_dir) / f"resume_{slug}.md"
                write_tailored_resume(tailored, str(resume_path))
                manifest_job["resume_file"] = str(resume_path.resolve())
                manifest_job["keyword_match_score"] = tailored.keyword_match_score

                # Write to persistent resumes store
                persistent_path = resumes_daily_dir / f"{slug}.md"
                write_tailored_resume(tailored, str(persistent_path))

                # Update resume index (pointer registry)
                resume_index["resumes"][slug] = {  # type: ignore[index]
                    "company": company,
                    "role": role,
                    "score": manifest_job.get("score", 0),
                    "keyword_match_score": tailored.keyword_match_score,
                    "apply_url": manifest_job.get("apply_url", ""),
                    "resume_path": str(persistent_path.relative_to(Path(args.daily_output_root).parent)),
                    "date": run_date.isoformat(),
                }

                tailored_count += 1

            # Write index.json at resumes root
            index_path.write_text(json.dumps(resume_index, indent=2, sort_keys=False), encoding="utf-8")
            payload["tailored_resumes_written"] = tailored_count
            payload["resume_index"] = str(index_path)

        # Write manifest so the UI can load the correct resume per job automatically
        manifest: dict[str, object] = {
            "generated_on": run_date.isoformat(),
            "daily_dir": str(Path(drafts_dir).parent.resolve()),
            "base_resume_used": args.base_resume,
            "jobs": manifest_jobs,
        }
        manifest_path = Path(drafts_dir).parent / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=False), encoding="utf-8")
        payload["manifest"] = str(manifest_path)

    if args.write_macos_launchd:
        program_args = build_daily_program_args(
            python_executable=sys.executable,
            input_path=args.input,
            daily_output_root=args.daily_output_root,
            top=args.top,
            rss_urls=args.rss_url,
            rss_limit=args.rss_limit,
            rss_status=args.rss_status,
            no_dedupe=args.no_dedupe,
            require_visa_support=args.require_visa_support,
        )
        logs_dir = Path("logs")
        plist_bytes = build_launchd_plist(
            label=args.launchd_label,
            program_arguments=program_args,
            working_directory=str(Path.cwd()),
            hour=args.launchd_hour,
            minute=args.launchd_minute,
            stdout_path=str(logs_dir / "job_pipeline.out.log"),
            stderr_path=str(logs_dir / "job_pipeline.err.log"),
        )
        plist_path = Path(args.launchd_plist_path)
        write_launchd_plist(plist_path, plist_bytes)
        payload["launchd_plist_written"] = str(plist_path)

        if args.install_macos_launchd:
            agent_dir = Path(expanduser(args.launchd_agent_dir))
            installed_path = install_launchd_agent(plist_path, args.launchd_label, agent_dir)
            payload["launchd_installed"] = str(installed_path)

    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
