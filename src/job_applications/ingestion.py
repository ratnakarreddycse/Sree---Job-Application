from __future__ import annotations

import csv
import json
import re
import sys
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