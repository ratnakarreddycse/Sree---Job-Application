from __future__ import annotations

import csv
import json
import re
import sys
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen
from xml.etree import ElementTree

# Namespaces used by known RSS providers
_JOBICY_NS = "https://jobicy.com"
_REMOTIVE_NS = ""  # bare elements, no namespace


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace for clean plain text."""
    no_tags = re.sub(r"<[^>]+>", " ", text)
    no_entities = re.sub(r"&[a-zA-Z]+;|&#\d+;", " ", no_tags)
    return re.sub(r"\s+", " ", no_entities).strip()


def _find_element_text(item: ElementTree.Element, tag: str, *namespaces: str) -> str:
    """Return first non-empty text for tag, trying bare tag then each namespace."""
    el = item.find(tag)
    if el is not None and el.text and el.text.strip():
        return el.text.strip()
    for ns in namespaces:
        el = item.find(f"{{{ns}}}{tag}")
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return ""


def load_records_from_file(input_path: Path) -> list[dict[str, str]]:
    suffix = input_path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        return [_normalize_raw_record(item) for item in payload if isinstance(item, dict)]

    if suffix == ".csv":
        with input_path.open("r", encoding="utf-8", newline="") as file_obj:
            reader = csv.DictReader(file_obj)
            return [_normalize_raw_record(dict(row)) for row in reader]

    raise ValueError(f"Unsupported input format: {suffix}. Use .json or .csv")


def fetch_rss_records(urls: Iterable[str], limit_per_feed: int = 25, default_status: str = "new") -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for url in urls:
        try:
            request = Request(url=url, headers={"User-Agent": "job-applications-pipeline/0.1"})
            with urlopen(request, timeout=20) as response:
                xml_content = response.read()
        except (URLError, OSError) as exc:
            print(f"[rss] skipping {url!r}: {exc}", file=sys.stderr)
            continue

        try:
            root = ElementTree.fromstring(xml_content)
        except ElementTree.ParseError as exc:
            print(f"[rss] skipping {url!r}: invalid XML — {exc}", file=sys.stderr)
            continue

        items = root.findall(".//item")
        for item in items[: max(limit_per_feed, 0)]:
            title = _text_or_empty(item.find("title")).strip()

            # Company: try dedicated element first (Remotive, RemoteOK, Jobicy), else parse title
            company_from_el = _find_element_text(item, "company", _JOBICY_NS)
            if company_from_el:
                company = company_from_el
                role = title
            else:
                company, role = _extract_company_and_role(title)

            # Description: strip HTML for clean notes / keyword matching
            raw_description = _text_or_empty(item.find("description"))
            description = _strip_html(raw_description)

            # Location hints from feed (WWR, Jobicy, RemoteOK)
            location = _find_element_text(item, "location", _JOBICY_NS)
            link = _text_or_empty(item.find("link"))

            notes_parts = [description]
            if location:
                notes_parts.append(f"Location: {location}")
            notes_parts.append(f"Source: {url}")
            if link:
                notes_parts.append(f"Link: {link}")

            records.append(
                {
                    "company": company,
                    "role": role,
                    "status": default_status,
                    "notes": " ".join(notes_parts).strip(),
                    "apply_url": link,
                }
            )

    return records


def fetch_ats_records(
    ats_boards: list[dict],
    limit_per_board: int = 10,
    default_status: str = "new",
) -> list[dict[str, str]]:
    """Fetch live job postings from ATS job board APIs (Greenhouse, Lever, Ashby).

    Each board config dict must have:
        type:     "greenhouse" | "lever" | "ashby"
        slug:     company slug in the ATS board URL
        company:  human-readable company name (defaults to slug)
        keywords: list of strings — only return jobs whose title contains at least one
        limit:    per-board override for max records returned (optional)

    Returns records with apply_url pointing directly to the specific job posting.
    """
    records: list[dict[str, str]] = []
    for board in ats_boards:
        board_type = board.get("type", "").lower()
        slug = board.get("slug", "").strip()
        company = board.get("company", slug) or slug
        keywords = [kw.lower() for kw in board.get("keywords", [])]
        board_limit = int(board.get("limit", limit_per_board))

        if not slug:
            continue

        location_filter = [lf.lower() for lf in board.get("location_filter", [])]

        try:
            if board_type == "greenhouse":
                records.extend(_fetch_greenhouse_jobs(slug, company, keywords, board_limit, default_status, location_filter))
            elif board_type == "lever":
                records.extend(_fetch_lever_jobs(slug, company, keywords, board_limit, default_status, location_filter))
            elif board_type == "ashby":
                records.extend(_fetch_ashby_jobs(slug, company, keywords, board_limit, default_status, location_filter))
            else:
                print(f"[ats] unknown board type {board_type!r} for {company!r}", file=sys.stderr)
        except (URLError, OSError) as exc:
            print(f"[ats] skipping {board_type}:{slug} — {exc}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[ats] error fetching {board_type}:{slug} — {exc}", file=sys.stderr)

    return records


def _ats_request(url: str) -> object:
    """GET an ATS API URL and return parsed JSON."""
    req = Request(url=url, headers={"User-Agent": "job-applications-pipeline/0.1"})
    with urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    """Return True when text contains at least one keyword, or keywords is empty."""
    if not keywords:
        return True
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _matches_location(location: str, location_filter: list[str]) -> bool:
    """Return True if location_filter is empty, or any filter term appears in the location (case-insensitive)."""
    if not location_filter:
        return True
    loc_lower = location.lower()
    return any(term in loc_lower for term in location_filter)


def _fetch_greenhouse_jobs(
    slug: str,
    company: str,
    keywords: list[str],
    limit: int,
    default_status: str,
    location_filter: list[str] | None = None,
) -> list[dict[str, str]]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    data = _ats_request(url)
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    location_filter = location_filter or []
    records: list[dict[str, str]] = []
    for job in jobs:
        title = str(job.get("title", "")).strip()
        apply_url = str(job.get("absolute_url", "")).strip()
        loc_raw = job.get("location", {})
        location = str(loc_raw.get("name", "")).strip() if isinstance(loc_raw, dict) else ""
        raw_content = job.get("content", "") or ""
        # Greenhouse returns HTML-entity-encoded HTML (e.g. &lt;div&gt;) —
        # unescape first so _strip_html sees real <tag> patterns to remove.
        description = _strip_html(unescape(str(raw_content)))[:5000]

        if not _matches_keywords(title, keywords):
            continue
        if not _matches_location(location, location_filter):
            continue

        notes_parts = []
        if description:
            notes_parts.append(description)
        if location:
            notes_parts.append(f"Location: {location}")
        notes_parts.append(f"Source: Greenhouse/{slug}")
        if apply_url:
            notes_parts.append(f"Link: {apply_url}")

        records.append({
            "company": company,
            "role": title,
            "status": default_status,
            "notes": " ".join(notes_parts).strip(),
            "apply_url": apply_url,
            "location": location,
        })
        if len(records) >= limit:
            break

    return records


def _fetch_lever_jobs(
    slug: str,
    company: str,
    keywords: list[str],
    limit: int,
    default_status: str,
    location_filter: list[str] | None = None,
) -> list[dict[str, str]]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=250"
    data = _ats_request(url)
    jobs = data if isinstance(data, list) else []
    location_filter = location_filter or []
    records: list[dict[str, str]] = []
    for job in jobs:
        title = str(job.get("text", "")).strip()
        apply_url = str(job.get("hostedUrl", "")).strip()
        categories = job.get("categories") or {}
        location = str(categories.get("location", "")).strip() if isinstance(categories, dict) else ""
        description = str(job.get("descriptionPlain", "")).strip()

        if not _matches_keywords(f"{title} {description}", keywords):
            continue
        if not _matches_location(location, location_filter):
            continue

        notes_parts = []
        if location:
            notes_parts.append(f"Location: {location}")
        notes_parts.append(f"Source: Lever/{slug}")
        if apply_url:
            notes_parts.append(f"Link: {apply_url}")

        records.append({
            "company": company,
            "role": title,
            "status": default_status,
            "notes": " ".join(notes_parts).strip(),
            "apply_url": apply_url,
            "location": location,
        })
        if len(records) >= limit:
            break

    return records


def _fetch_ashby_jobs(
    slug: str,
    company: str,
    keywords: list[str],
    limit: int,
    default_status: str,
    location_filter: list[str] | None = None,
) -> list[dict[str, str]]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    data = _ats_request(url)
    jobs = data.get("jobs", []) if isinstance(data, dict) else []
    location_filter = location_filter or []
    records: list[dict[str, str]] = []
    for job in jobs:
        title = str(job.get("title", "")).strip()
        apply_url = str(job.get("jobUrl", "")).strip()
        location = str(job.get("location", "")).strip()
        description = str(job.get("descriptionPlain", "")).strip()

        if not _matches_keywords(f"{title} {description}", keywords):
            continue
        if not _matches_location(location, location_filter):
            continue

        notes_parts = []
        if location:
            notes_parts.append(f"Location: {location}")
        notes_parts.append(f"Source: Ashby/{slug}")
        if apply_url:
            notes_parts.append(f"Link: {apply_url}")

        records.append({
            "company": company,
            "role": title,
            "status": default_status,
            "notes": " ".join(notes_parts).strip(),
            "apply_url": apply_url,
            "location": location,
        })
        if len(records) >= limit:
            break

    return records


def dedupe_records(records: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, str]] = []

    for record in records:
        company = record.get("company", "").strip().lower()
        role = record.get("role", "").strip().lower()
        notes = record.get("notes", "").strip().lower()
        key = (company, role, notes)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)

    return deduped


def _normalize_raw_record(raw_record: dict[str, object]) -> dict[str, str]:
    company = _get_first(raw_record, ["company", "employer", "organization"])
    role = _get_first(raw_record, ["role", "title", "job_title", "position"])
    status = _get_first(raw_record, ["status", "application_status"]) or "new"
    notes = _get_first(raw_record, ["notes", "description", "summary", "details"]) or ""
    apply_url = _get_first(raw_record, ["apply_url", "job_url", "url", "link"]) or ""

    # Embed URL in notes so keyword scoring still picks it up (backwards compat).
    if apply_url and "link:" not in notes.lower():
        notes = f"{notes} Link: {apply_url}".strip()

    return {
        "company": company,
        "role": role,
        "status": status,
        "notes": notes,
        "apply_url": apply_url,
    }


def _get_first(raw_record: dict[str, object], keys: list[str]) -> str:
    for key in keys:
        value = raw_record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _text_or_empty(element: ElementTree.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def _extract_company_and_role(title: str) -> tuple[str, str]:
    """Parse company and role from a job title string.

    Handles common RSS title patterns:
    - "Role at Company"  (LinkedIn-style)
    - "Company: Role - Sub"  (We Work Remotely style)
    - "Company - Role"  (generic dash-separated)
    - Bare role only  (Remotive / Jobicy — company comes from XML element)
    """
    cleaned = title.strip()

    # "Role at Company"
    lower = cleaned.lower()
    if " at " in lower:
        idx = lower.index(" at ")
        return cleaned[idx + 4:].strip(), cleaned[:idx].strip()

    # "Company: Role ..." — colon separator (We Work Remotely)
    if ": " in cleaned:
        company_part, role_part = cleaned.split(": ", 1)
        # WWR sometimes appends " - Sub-title" after the role
        role_only = role_part.split(" - ")[0].strip() if " - " in role_part else role_part.strip()
        return company_part.strip(), role_only

    # "Company - Role" — dash separator
    if " - " in cleaned:
        left, right = cleaned.split(" - ", 1)
        return left.strip(), right.strip()

    return "Unknown", cleaned


# ---------------------------------------------------------------------------
# Workday ATS fetcher
# ---------------------------------------------------------------------------

def fetch_workday_records(
    boards: list[dict],
    limit_per_board: int = 10,
    default_status: str = "new",
) -> list[dict[str, str]]:
    """Fetch live job postings from Workday's public jobs API (no auth required).

    Each board config dict:
        type:            "workday"
        domain:          full Workday domain, e.g. "salesforce.wd12.myworkdayjobs.com"
        page:            Workday tenant/page slug visible in the careers URL, e.g. "Careers"
        company:         human-readable company name
        keywords:        list of strings — only jobs whose title matches at least one
        location_filter: optional list of location terms to restrict results
        limit:           per-board max records (optional, defaults to limit_per_board)

    To find your target company's domain+page: visit their careers site and note
    the URL pattern: https://{domain}/en-US/{page}/jobs
    """
    records: list[dict[str, str]] = []
    for board in boards:
        domain = board.get("domain", "").strip()
        page = board.get("page", "").strip()
        company = board.get("company") or domain.split(".")[0]
        keywords = [kw.lower() for kw in board.get("keywords", [])]
        board_limit = int(board.get("limit", limit_per_board))
        location_filter = [lf.lower() for lf in board.get("location_filter", [])]

        if not domain or not page:
            continue

        tenant = domain.split(".")[0]
        url = f"https://{domain}/wday/cxs/{tenant}/{page}/jobs"
        try:
            body = json.dumps({"limit": 20, "offset": 0}).encode("utf-8")
            req = Request(
                url, data=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Referer": f"https://{domain}/en-US/{page}",
                    "X-Requested-With": "XMLHttpRequest",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                },
            )
            with urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (URLError, OSError) as exc:
            print(f"[workday] skipping {company}: {exc}", file=sys.stderr)
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"[workday] error for {company}: {exc}", file=sys.stderr)
            continue

        jobs = data.get("jobPostings", []) if isinstance(data, dict) else []
        count = 0
        for job in jobs:
            title = str(job.get("title", "")).strip()
            path = str(job.get("externalPath", "")).strip()
            location = str(job.get("locationsText", "")).strip()

            if not title:
                continue
            if not _matches_keywords(title, keywords):
                continue
            if not _matches_location(location, location_filter):
                continue

            apply_url = f"https://{domain}/en-US/{page}{path}" if path else ""
            notes_parts = []
            if location:
                notes_parts.append(f"Location: {location}")
            notes_parts.append(f"Source: Workday/{domain}")
            if apply_url:
                notes_parts.append(f"Link: {apply_url}")

            records.append({
                "company": company,
                "role": title,
                "status": default_status,
                "notes": " ".join(notes_parts).strip(),
                "apply_url": apply_url,
                "location": location,
            })
            count += 1
            if count >= board_limit:
                break

    return records


# ---------------------------------------------------------------------------
# SmartRecruiters ATS fetcher
# ---------------------------------------------------------------------------

def fetch_smartrecruiters_records(
    boards: list[dict],
    limit_per_board: int = 10,
    default_status: str = "new",
) -> list[dict[str, str]]:
    """Fetch live job postings from SmartRecruiters public API (no auth required).

    Each board config dict:
        type:            "smartrecruiters"
        slug:            company slug on SmartRecruiters (typically lowercase company name)
        company:         human-readable name (defaults to slug)
        keywords:        list of strings — only jobs whose title matches at least one
        location_filter: optional list of location terms to restrict results
        limit:           per-board max records (optional)

    To find a slug: visit jobs.smartrecruiters.com/{slug} and check it returns results.
    """
    records: list[dict[str, str]] = []
    for board in boards:
        slug = board.get("slug", "").strip()
        company = board.get("company", slug) or slug
        keywords = [kw.lower() for kw in board.get("keywords", [])]
        board_limit = int(board.get("limit", limit_per_board))
        location_filter = [lf.lower() for lf in board.get("location_filter", [])]

        if not slug:
            continue

        url = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset=0"
        try:
            data = _ats_request(url)
        except (URLError, OSError) as exc:
            print(f"[smartrecruiters] skipping {company}: {exc}", file=sys.stderr)
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"[smartrecruiters] error for {company}: {exc}", file=sys.stderr)
            continue

        jobs = data.get("content", []) if isinstance(data, dict) else []
        count = 0
        for job in jobs:
            title = str(job.get("name", "")).strip()
            apply_url = str(job.get("ref", "")).strip()
            location_data = job.get("location") or {}
            city = str(location_data.get("city", "")).strip() if isinstance(location_data, dict) else ""
            country = str(location_data.get("country", "")).strip() if isinstance(location_data, dict) else ""
            remote_flag = location_data.get("remote", False) if isinstance(location_data, dict) else False

            loc_parts: list[str] = []
            if remote_flag:
                loc_parts.append("Remote")
            if city:
                loc_parts.append(city)
            if country:
                loc_parts.append(country)
            location = ", ".join(loc_parts)

            if not title:
                continue
            if not _matches_keywords(title, keywords):
                continue
            if not _matches_location(location, location_filter):
                continue

            notes_parts = []
            if location:
                notes_parts.append(f"Location: {location}")
            notes_parts.append(f"Source: SmartRecruiters/{slug}")
            if apply_url:
                notes_parts.append(f"Link: {apply_url}")

            records.append({
                "company": company,
                "role": title,
                "status": default_status,
                "notes": " ".join(notes_parts).strip(),
                "apply_url": apply_url,
                "location": location,
            })
            count += 1
            if count >= board_limit:
                break

    return records


# ---------------------------------------------------------------------------
# JSearch API fetcher (covers LinkedIn, Indeed, Glassdoor, ZipRecruiter, Dice, etc.)
# ---------------------------------------------------------------------------

def fetch_jsearch_records(
    queries: list[str],
    api_key: str,
    num_pages_per_query: int = 1,
    default_status: str = "new",
) -> list[dict[str, str]]:
    """Fetch job postings via JSearch API (RapidAPI).

    JSearch aggregates Google for Jobs, covering LinkedIn, Indeed, Glassdoor,
    ZipRecruiter, Dice, Builtin, and virtually every public job site in one call.

    Free tier: 200 requests/month — https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
    Set environment variable JSEARCH_API_KEY to your RapidAPI key.

    Args:
        queries:               list of search strings sent to the API
        api_key:               RapidAPI key (skips silently when empty)
        num_pages_per_query:   pages per query — each page returns 10 jobs (default: 1)
        default_status:        status assigned to fetched records
    """
    records: list[dict[str, str]] = []
    if not api_key:
        return records

    for query in queries:
        for page in range(1, num_pages_per_query + 1):
            encoded_query = query.replace(" ", "%20").replace("&", "%26")
            url = (
                f"https://jsearch.p.rapidapi.com/search"
                f"?query={encoded_query}&page={page}&num_pages=1&date_posted=week"
            )
            req = Request(
                url,
                headers={
                    "X-RapidAPI-Key": api_key,
                    "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
                    "User-Agent": "job-applications-pipeline/0.1",
                },
            )
            try:
                with urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except (URLError, OSError) as exc:
                print(f"[jsearch] skipping query {query!r}: {exc}", file=sys.stderr)
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[jsearch] error for query {query!r}: {exc}", file=sys.stderr)
                break

            if data.get("status") != "OK":
                print(
                    f"[jsearch] non-OK response for {query!r}: {data.get('message', '')}",
                    file=sys.stderr,
                )
                break

            for job in data.get("data", []):
                title = str(job.get("job_title", "")).strip()
                employer = str(job.get("employer_name", "")).strip()
                apply_url = str(job.get("job_apply_link", "")).strip()
                description = _strip_html(str(job.get("job_description", ""))).strip()[:800]
                city = str(job.get("job_city", "")).strip()
                state = str(job.get("job_state", "")).strip()
                country = str(job.get("job_country", "")).strip()
                is_remote = bool(job.get("job_is_remote", False))

                loc_parts: list[str] = []
                if is_remote:
                    loc_parts.append("Remote")
                if city:
                    loc_parts.append(city)
                if state:
                    loc_parts.append(state)
                if country and country.upper() not in {"US", "USA"}:
                    loc_parts.append(country)
                location = ", ".join(loc_parts)

                if not title or not employer:
                    continue

                notes_parts: list[str] = []
                if description:
                    notes_parts.append(description)
                if location:
                    notes_parts.append(f"Location: {location}")
                notes_parts.append(f"Source: JSearch/{query}")
                if apply_url:
                    notes_parts.append(f"Link: {apply_url}")

                records.append({
                    "company": employer,
                    "role": title,
                    "status": default_status,
                    "notes": " ".join(notes_parts).strip(),
                    "apply_url": apply_url,
                    "location": location,
                })

    return records


# ---------------------------------------------------------------------------
# Cross-source deduplication / merging
# ---------------------------------------------------------------------------

def _simple_url_score(url: str) -> int:
    """Quick heuristic: higher score = more likely a direct job-posting URL."""
    if not url or not url.startswith(("http://", "https://")):
        return -1
    path = url.split("?")[0].rstrip("/")
    score = len(path.split("/"))  # more path segments → more specific
    if any(c.isdigit() for c in path):
        score += 2  # numeric ID in path is a strong signal
    if "search" in path.lower() or "jobs?" in url.lower():
        score -= 4  # search/listing page penalty
    return score


def merge_duplicate_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    """Merge records sharing the same (company, role) found across multiple sources.

    Benefits:
    - Combines notes from all sources so keyword scoring sees the richest signal.
    - Selects the most specific apply URL (direct posting over listing page).
    - Prevents the same job from occupying multiple slots in the top-N output.
    """
    # Preserve insertion order of first occurrence.
    order: dict[tuple[str, str], int] = {}
    groups: dict[tuple[str, str], list[dict[str, str]]] = {}

    for idx, record in enumerate(records):
        company = record.get("company", "").strip().lower()
        role = record.get("role", "").strip().lower()
        if not company or not role:
            continue
        key = (company, role)
        if key not in order:
            order[key] = idx
        groups.setdefault(key, []).append(record)

    merged: list[dict[str, str]] = []
    for key, group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
            continue

        base = dict(group[0])
        seen_notes: list[str] = []
        best_url = ""
        best_url_score = -999

        for rec in group:
            note = rec.get("notes", "").strip()
            if note and note not in seen_notes:
                seen_notes.append(note)
            url = rec.get("apply_url", "").strip()
            if url:
                s = _simple_url_score(url)
                if s > best_url_score:
                    best_url_score = s
                    best_url = url

        base["notes"] = " ".join(seen_notes)
        if best_url:
            base["apply_url"] = best_url
        merged.append(base)

    merged.sort(key=lambda r: order.get(
        (r.get("company", "").strip().lower(), r.get("role", "").strip().lower()), 0
    ))
    return merged