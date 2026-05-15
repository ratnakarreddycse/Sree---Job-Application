from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import webbrowser
from copy import deepcopy
from dataclasses import dataclass
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class UiConfig:
    input_path: str | None
    daily_output_root: str
    top: int
    base_resume: str | None = None
    rss_urls: list[str] | None = None
    portal_config_path: str | None = None

    def __post_init__(self) -> None:
        if self.rss_urls is None:
            object.__setattr__(self, "rss_urls", [])


DEFAULT_ANSWER_MEMORY: dict[str, Any] = {
    "profile": {
        "full_name": "",
        "email": "",
        "phone": "",
        "linkedin": "",
        "location": "",
        "work_authorization": "",
        "needs_sponsorship": "",
    },
    "questions": {},
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start a local UI for assisted job applications")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the local UI server")
    parser.add_argument("--port", type=int, default=8765, help="Port for the local UI server")
    parser.add_argument(
        "--config",
        default="portal_config.json",
        help="Path to portal config JSON. Missing file will use defaults.",
    )
    parser.add_argument("--open-browser", action="store_true", help="Open UI page automatically in browser")
    return parser


def _as_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def load_ui_config(path: Path) -> UiConfig:
    if not path.exists():
        return UiConfig(input_path=None, daily_output_root="outputs", top=0)

    payload = json.loads(path.read_text(encoding="utf-8"))
    rss_urls = [str(u) for u in payload.get("rss_urls", []) if str(u).strip()]

    return UiConfig(
        input_path=_as_optional_text(payload.get("input_path")),
        daily_output_root=_as_optional_text(payload.get("daily_output_root")) or "outputs",
        top=_as_int(payload.get("top"), fallback=0),
        base_resume=_as_optional_text(payload.get("base_resume")),
        rss_urls=rss_urls,
        portal_config_path=str(path) if path.exists() else None,
    )


def build_pipeline_command(config: UiConfig) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "job_applications.cli",
        "--daily-run",
        "--daily-output-root",
        config.daily_output_root,
        "--top",
        str(config.top),
    ]
    if config.input_path:
        command.extend(["--input", config.input_path])
    if config.base_resume:
        command.extend(["--base-resume", config.base_resume])
    for url in (config.rss_urls or []):
        command.extend(["--rss-url", url])
    if config.portal_config_path:
        command.extend(["--portal-config", config.portal_config_path])
    return command


def _find_latest_manifest(daily_output_root: str) -> dict[str, Any] | None:
    root = Path(daily_output_root)
    if not root.is_dir():
        return None
    dated_dirs = sorted(
        (d for d in root.iterdir() if d.is_dir() and len(d.name) == 10 and d.name[4] == "-"),
        reverse=True,
    )
    for d in dated_dirs:
        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            try:
                return json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
    return None


def _safe_open_path(path_str: str, daily_output_root: str) -> tuple[bool, str]:
    try:
        target = Path(path_str).resolve()
        root = Path(daily_output_root).resolve()
    except (TypeError, ValueError):
        return False, "Invalid path"

    if not str(target).startswith(str(root)):
        return False, "Path outside allowed directory"
    if target.suffix.lower() not in {".md", ".json", ".txt"}:
        return False, "File type not allowed"
    if not target.exists():
        return False, f"File not found: {target}"

    try:
        subprocess.run(["open", str(target)], check=True)
        return True, str(target)
    except subprocess.CalledProcessError as exc:
        return False, str(exc)


def _looks_like_listing_url(url_str: str) -> bool:
    parsed = urlparse(url_str)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower().rstrip("/")
    query = parse_qs(parsed.query.lower())

    # ── Specific job posting: path contains a long numeric or hex-heavy ID ─────
    # e.g. /company/careers/engineering/senior-data-engineer-8229672002
    #      /us/en/job/SNCOUS4414B8D6.../Senior-Solution-Engineer
    # These are never listing pages regardless of other tokens in the path.
    if re.search(r"\d{5,}", path):
        return False

    # ── Server-rendered ATS board root pages ──────────────────────────────────
    # boards.greenhouse.io/<company>  or  job-boards.greenhouse.io/<company>  or
    # jobs.lever.co/<company> are listing pages (one path segment = company slug,
    # no job ID). They ARE server-rendered so the HTML scraper can find role links.
    if netloc in _SCRAPABLE_ATS_HOSTS:
        segments = [s for s in path.split("/") if s]
        # Listing root = just the company slug (≤1 segment, no numeric job ID)
        if len(segments) <= 1:
            return True
        # Also flag search/filter pages on these hosts
        if any(key in query for key in ["search", "query", "keywords", "q"]):
            return True

    # Workday job sites are always listing roots at the host level
    if netloc.endswith(".myworkdayjobs.com"):
        return True

    # ── Generic listing path / query patterns ─────────────────────────────────
    listing_paths = {
        "",
        "/",
        "/careers",
        "/jobs",
        "/company/careers",
        "/company/careers/open-positions",
        "/search-results",
        "/us/en/search-results",
    }
    if path in listing_paths:
        return True

    # Tokens that indicate a search/listing page rather than a specific posting.
    # Note: "careers" alone is intentionally excluded here — many direct job
    # posting URLs contain "/careers/" as a path prefix (e.g. Databricks).
    listing_tokens = ["search", "open-positions", "open_positions"]
    if any(token in path for token in listing_tokens):
        return True

    # Paths that are just "/careers" or "/careers/" at depth ≤1 are listings.
    if re.match(r"^/careers/?$", path):
        return True

    if any(key in query for key in ["search", "query", "keywords", "department", "location"]):
        return True

    # A direct job posting URL typically has a numeric job ID in the path.
    if re.search(r"/jobs?/[^/]*\d+", path):
        return False

    return False


# Hosts whose job board HTML is server-rendered and can be reliably scraped with
# urlopen. Modern company career sites (databricks.com, careers.snowflake.com,
# stripe.com, careers.confluent.io, etc.) are JavaScript SPAs — urlopen returns
# skeleton HTML, causing the scraper to pick navigation links or the wrong role.
_SCRAPABLE_ATS_HOSTS: frozenset[str] = frozenset({
    "boards.greenhouse.io",
    "boards.eu.greenhouse.io",
    "job-boards.greenhouse.io",
    "jobs.lever.co",
})


def _normalize_words(value: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", value.lower()) if len(w) > 2]


def _pick_best_link_from_html(listing_url: str, html: str, role: str, company: str) -> str | None:
    anchors = re.findall(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, flags=re.IGNORECASE | re.DOTALL)
    if not anchors:
        return None

    role_words = set(_normalize_words(role))
    company_words = set(_normalize_words(company))
    listing_path = urlparse(listing_url).path.lower().rstrip("/")
    listing_host = urlparse(listing_url).netloc.lower()
    best_score: int = 0
    best_url: str | None = None

    for raw_href, raw_text in anchors:
        href = unescape(raw_href).strip()
        if href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("#"):
            continue

        absolute_url = urljoin(listing_url, href)
        parsed = urlparse(absolute_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if listing_host and parsed.netloc.lower() != listing_host:
            continue

        path = parsed.path.lower().rstrip("/")
        if path == listing_path:
            continue

        text = unescape(re.sub(r"<[^>]+>", " ", raw_text))
        words = set(_normalize_words(f"{text} {path}"))

        score = 0
        score += len(role_words.intersection(words)) * 4
        score += len(company_words.intersection(words))

        if any(token in path for token in ["/job/", "/jobs/", "/position/", "/positions/"]):
            score += 5
        if re.search(r"\d", path):
            score += 2
        if _looks_like_listing_url(absolute_url):
            score -= 4

        if score <= 0:
            continue

        if best_url is None or score > best_score:
            best_score = score
            best_url = absolute_url

    if best_url is None:
        return None
    return best_url


def _resolve_direct_apply_url(url_str: str, role: str, company: str) -> str:
    # Only attempt HTML scraping for known server-rendered ATS boards.
    # For all other URLs (company career sites), return as-is so the user
    # lands on the correct search/listing page rather than a wrong page.
    parsed_host = urlparse(url_str).netloc.lower()
    if parsed_host not in _SCRAPABLE_ATS_HOSTS:
        return url_str

    if not _looks_like_listing_url(url_str):
        return url_str

    try:
        request = Request(url=url_str, headers={"User-Agent": "job-applications-ui/0.1"})
        with urlopen(request, timeout=10) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return url_str
            html = response.read().decode("utf-8", errors="ignore")
    except OSError:
        return url_str

    resolved = _pick_best_link_from_html(url_str, html, role=role, company=company)
    return resolved or url_str


def _safe_open_url(url_str: str, role: str = "", company: str = "") -> tuple[bool, str]:
    parsed = urlparse(url_str)
    if parsed.scheme not in {"http", "https"}:
        return False, "Only http/https URLs are allowed"
    if not parsed.netloc:
        return False, "Invalid URL"

    final_url = _resolve_direct_apply_url(url_str, role=role, company=company)
    webbrowser.open_new_tab(final_url)

    if final_url != url_str:
        return True, f"Opened direct posting: {final_url}"
    return True, final_url


def _answer_memory_path(daily_output_root: str) -> Path:
    root = Path(daily_output_root).resolve()
    return root.parent / "answers_memory.json"


def _load_answer_memory(daily_output_root: str) -> dict[str, Any]:
    path = _answer_memory_path(daily_output_root)
    if not path.exists():
        return deepcopy(DEFAULT_ANSWER_MEMORY)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return deepcopy(DEFAULT_ANSWER_MEMORY)

    memory = deepcopy(DEFAULT_ANSWER_MEMORY)
    if isinstance(payload.get("profile"), dict):
        for key in memory["profile"]:
            value = payload["profile"].get(key)
            if value is not None:
                memory["profile"][key] = str(value)
    if isinstance(payload.get("questions"), dict):
        memory["questions"] = {str(k): str(v) for k, v in payload["questions"].items() if str(k).strip()}
    return memory


def _save_answer_memory(daily_output_root: str, memory: dict[str, Any]) -> tuple[bool, str]:
    path = _answer_memory_path(daily_output_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(memory, indent=2, sort_keys=True), encoding="utf-8")
        return True, str(path)
    except OSError as exc:
        return False, str(exc)


def _inline_md(text: str) -> str:
    """Convert inline markdown (bold, italic) to HTML entities."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    return text


def _md_to_html_doc(md_content: str) -> str:
    """Convert resume markdown to a full ATS-styled HTML document for PDF printing."""
    lines = md_content.splitlines()
    body_parts: list[str] = []
    in_ul = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_ul:
                body_parts.append("</ul>")
                in_ul = False
            continue
        if stripped.startswith("### "):
            if in_ul:
                body_parts.append("</ul>")
                in_ul = False
            body_parts.append(f"<h3>{_inline_md(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            if in_ul:
                body_parts.append("</ul>")
                in_ul = False
            body_parts.append(f"<h2>{_inline_md(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            if in_ul:
                body_parts.append("</ul>")
                in_ul = False
            body_parts.append(f"<h1>{_inline_md(stripped[2:])}</h1>")
        elif stripped.startswith("- "):
            if not in_ul:
                body_parts.append("<ul>")
                in_ul = True
            body_parts.append(f"<li>{_inline_md(stripped[2:])}</li>")
        else:
            if in_ul:
                body_parts.append("</ul>")
                in_ul = False
            body_parts.append(f"<p>{_inline_md(stripped)}</p>")

    if in_ul:
        body_parts.append("</ul>")

    body_html = "\n".join(body_parts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: "Times New Roman", Times, serif;
    font-size: 11pt; line-height: 1.45; color: #000;
    padding: 0.6in 0.65in; max-width: 8.5in;
  }}
  h1 {{ font-size:17pt; font-weight:bold; text-align:center; margin-bottom:3px; }}
  h1 + p {{ text-align:center; font-size:10pt; color:#333; margin-bottom:12px; }}
  h2 {{
    font-size:11pt; font-weight:bold; text-transform:uppercase;
    letter-spacing:0.04em; border-bottom:1.5px solid #000;
    padding-bottom:2px; margin-top:12px; margin-bottom:5px;
  }}
  h3 {{ font-size:11pt; font-weight:bold; margin-top:8px; margin-bottom:0; }}
  h3 + p {{ font-size:10pt; color:#333; font-style:italic; margin-bottom:3px; }}
  ul {{ margin:3px 0 3px 16px; }}
  li {{ font-size:10.5pt; margin-bottom:2px; }}
  p {{ font-size:10.5pt; margin-bottom:4px; }}
  strong {{ font-weight:bold; }} em {{ font-style:italic; }}
</style>
</head>
<body>
{body_html}
</body></html>"""


def _find_chrome_binary() -> str | None:
    """Locate Google Chrome or Chromium on macOS/Linux."""
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")


def _html_to_pdf(html_path: Path, pdf_path: Path) -> tuple[bool, str]:
    """Convert HTML to PDF using headless Chrome."""
    chrome = _find_chrome_binary()
    if not chrome:
        return False, "Google Chrome not found. Install Chrome to enable automatic PDF generation."
    try:
        result = subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-extensions",
                "--run-all-compositor-stages-before-draw",
                "--no-pdf-header-footer",
                f"--print-to-pdf={pdf_path}",
                f"file://{html_path}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if pdf_path.exists():
            return True, str(pdf_path)
        return False, f"Chrome exited {result.returncode}: {result.stderr[:300]}"
    except subprocess.TimeoutExpired:
        return False, "Chrome timed out generating PDF"
    except OSError as exc:
        return False, str(exc)


def _prep_resume_pdf(url: str, slug: str, daily_output_root: str) -> tuple[bool, str, str]:
    """
    Find the resume for a job (by slug or URL), convert to PDF, place in ~/Downloads/.
    Returns (ok, pdf_absolute_path, filename_or_error_message).
    """
    resumes_root = Path(daily_output_root).parent / "resumes"
    index_path = resumes_root / "index.json"
    downloads_dir = Path.home() / "Downloads"

    if not index_path.exists():
        return False, "", "No resume index found. Run the pipeline first."

    try:
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "", "Could not read resume index."

    resumes = index_data.get("resumes", {})

    def _extract_job_id(u: str) -> str | None:
        m = re.search(r"[?&/](?:gh_jid|jobId|id)[=\/](\d+)", u, re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.search(r"/(\d{6,})", u)
        return m.group(1) if m else None

    # Resolve slug from URL if not provided directly
    if not slug and url:
        url_id = _extract_job_id(url)
        try:
            url_host = urlparse(url).hostname or ""
        except Exception:
            url_host = ""
        best_slug: str | None = None
        for s, entry in resumes.items():
            apply_url = entry.get("apply_url", "")
            if not apply_url:
                continue
            entry_id = _extract_job_id(apply_url)
            if url_id and entry_id and url_id == entry_id:
                best_slug = s
                break
            if url_host and not best_slug:
                try:
                    entry_host = urlparse(apply_url).hostname or ""
                    if url_host == entry_host:
                        best_slug = s
                except Exception:
                    pass
        slug = best_slug or ""

    if not slug:
        return False, "", "No matching resume found for this URL."

    # Sanitize slug — only allow alphanumeric and hyphens (prevent path traversal)
    safe_slug = re.sub(r"[^a-z0-9\-]", "", slug.lower())
    if safe_slug != slug.lower().replace("_", "-"):
        return False, "", "Invalid slug format."

    entry = resumes.get(safe_slug)
    if not entry:
        return False, "", f"No resume entry for: {safe_slug}"

    resume_md_path = resumes_root.parent / entry["resume_path"]
    if not resume_md_path.exists():
        return False, "", f"Resume file not found: {resume_md_path}"

    # Build a human-readable PDF filename
    company_clean = re.sub(r"[^a-zA-Z0-9]", "_", entry.get("company", "Company")).strip("_")
    role_clean = re.sub(r"[^a-zA-Z0-9]", "_", entry.get("role", "Role")).strip("_")
    role_clean = re.sub(r"_+", "_", role_clean)
    pdf_filename = f"Ratnakar_Reddy_{company_clean}_{role_clean}.pdf"
    pdf_path = downloads_dir / pdf_filename

    # Convert .md → styled HTML → PDF
    md_content = resume_md_path.read_text(encoding="utf-8")
    html_content = _md_to_html_doc(md_content)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False, encoding="utf-8") as tmp:
        tmp.write(html_content)
        tmp_html = Path(tmp.name)

    try:
        ok, msg = _html_to_pdf(tmp_html, pdf_path)
    finally:
        tmp_html.unlink(missing_ok=True)

    if not ok:
        return False, "", msg

    return True, str(pdf_path), pdf_filename


def make_handler(config: UiConfig) -> type[BaseHTTPRequestHandler]:
    class UiHandler(BaseHTTPRequestHandler):
        def _send_json(self, payload: dict[str, Any], status_code: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str, status_code: int = 200) -> None:
            body = html.encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(_render_index_html(config))
                return
            if parsed.path == "/api/latest-jobs":
                manifest = _find_latest_manifest(config.daily_output_root)
                if manifest is None:
                    self._send_json({"ok": False, "message": "No pipeline runs found yet. Click Run Pipeline first.", "jobs": []})
                else:
                    self._send_json({"ok": True, "manifest": manifest})
                return
            if parsed.path == "/api/answers":
                self._send_json({"ok": True, "memory": _load_answer_memory(config.daily_output_root)})
                return
            if parsed.path == "/api/resume-index":
                index_path = Path(config.daily_output_root).parent / "resumes" / "index.json"
                if index_path.exists():
                    try:
                        index_data = json.loads(index_path.read_text(encoding="utf-8"))
                        self._send_json({"ok": True, "index": index_data})
                    except (OSError, json.JSONDecodeError):
                        self._send_json({"ok": False, "index": {}})
                else:
                    self._send_json({"ok": True, "index": {"resumes": {}}})
                return
            if parsed.path == "/api/prep-resume":
                query = parse_qs(parsed.query)
                slug = (query.get("slug") or [""])[0].strip()
                url = unquote((query.get("url") or [""])[0].strip())
                ok, pdf_path, filename_or_err = _prep_resume_pdf(url, slug, config.daily_output_root)
                if ok:
                    self._send_json({"ok": True, "pdf_path": pdf_path, "filename": filename_or_err})
                else:
                    self._send_json({"ok": False, "message": filename_or_err})
                return
            if parsed.path == "/api/open-downloads":
                downloads_dir = Path.home() / "Downloads"
                try:
                    subprocess.run(["open", str(downloads_dir)], check=True)
                    self._send_json({"ok": True})
                except subprocess.CalledProcessError as exc:
                    self._send_json({"ok": False, "message": str(exc)})
                return
            self._send_json({"error": "Not found"}, status_code=404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)

            if parsed.path == "/api/open-job":
                query = parse_qs(parsed.query)
                raw_url = unquote((query.get("url") or [""])[0].strip())
                role = unquote((query.get("role") or [""])[0].strip())
                company = unquote((query.get("company") or [""])[0].strip())
                ok, message = _safe_open_url(raw_url, role=role, company=company)
                self._send_json({"ok": ok, "message": message})
                return

            if parsed.path == "/api/run-pipeline":
                command = build_pipeline_command(config)
                result = subprocess.run(command, check=False, capture_output=True, text=True)
                self._send_json(
                    {
                        "ok": result.returncode == 0,
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "command": command,
                    },
                    status_code=200 if result.returncode == 0 else 500,
                )
                return

            if parsed.path == "/api/open-file":
                query = parse_qs(parsed.query)
                raw_path = unquote((query.get("path") or [""])[0].strip())
                ok, message = _safe_open_path(raw_path, config.daily_output_root)
                self._send_json({"ok": ok, "message": message})
                return

            if parsed.path == "/api/learn":
                length = int(self.headers.get("Content-Length", 0))
                body_bytes = self.rfile.read(length) if length > 0 else b""
                try:
                    payload_in = json.loads(body_bytes.decode("utf-8"))
                    question = str(payload_in.get("question", "")).strip()
                    answer = str(payload_in.get("answer", "")).strip()
                    if question and answer:
                        memory = _load_answer_memory(config.daily_output_root)
                        memory["questions"][question] = answer
                        _save_answer_memory(config.daily_output_root, memory)
                        self._send_json({"ok": True, "saved": question})
                    else:
                        self._send_json({"ok": False, "message": "question and answer required"})
                except (json.JSONDecodeError, KeyError):
                    self._send_json({"ok": False, "message": "invalid payload"}, status_code=400)
                return

            self._send_json({"error": "Not found"}, status_code=404)

    return UiHandler


def _render_index_html(config: UiConfig) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Job Apply Dashboard</title>
  <style>
    :root {{ --bg:#091428; --card:#0f172a; --text:#e2e8f0; --muted:#94a3b8; --accent:#38bdf8; --green:#34d399; --border:rgba(148,163,184,.2); }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Segoe UI,sans-serif; color:var(--text); background:linear-gradient(180deg,#0a162d,#020712); padding:22px; }}
    .wrap {{ max-width:1100px; margin:0 auto; }}
    .panel {{ background:rgba(15,23,42,.95); border:1px solid var(--border); border-radius:12px; padding:12px; margin-bottom:12px; }}
    h1 {{ margin:0 0 4px; font-size:1.9rem; }}
    .sub {{ margin:0 0 14px; color:var(--muted); font-size:.9rem; }}
    .portal-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(120px,1fr)); gap:8px; margin-bottom:10px; }}
    .portal-btn {{ border:1px solid var(--border); background:#0b1328; color:var(--text); border-radius:8px; padding:8px; font-size:.78rem; font-weight:700; cursor:pointer; }}
    .portal-btn:hover {{ border-color:var(--accent); }}
    .run-btn {{ width:100%; border:none; border-radius:10px; background:linear-gradient(90deg,#38bdf8,#34d399); color:#042433; font-size:.95rem; font-weight:700; padding:10px; cursor:pointer; }}
    .run-output {{ margin-top:8px; max-height:180px; overflow:auto; font-family:ui-monospace,monospace; font-size:.75rem; color:#cbd5e1; background:#020617; border:1px solid var(--border); border-radius:8px; padding:8px; white-space:pre-wrap; }}
    .raw-output-wrap {{ margin-top:8px; border:1px solid var(--border); border-radius:8px; background:#020617; }}
    .raw-output-wrap summary {{ cursor:pointer; padding:8px; color:#94a3b8; font-size:.75rem; user-select:none; }}
    .raw-output {{ max-height:220px; overflow:auto; padding:8px; border-top:1px solid rgba(148,163,184,.14); font-family:ui-monospace,monospace; font-size:.73rem; color:#cbd5e1; white-space:pre-wrap; }}
    .stats-row {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:8px; }}
    .stat-chip {{ border:1px solid var(--border); border-radius:8px; padding:4px 8px; color:#cbd5e1; font-size:.72rem; }}
    .jobs-head {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }}
    .refresh-btn {{ border:1px solid var(--accent); background:transparent; color:var(--accent); border-radius:8px; padding:5px 10px; font-size:.75rem; cursor:pointer; }}
    table {{ width:100%; border-collapse:collapse; font-size:.8rem; }}
    th, td {{ border-bottom:1px solid rgba(148,163,184,.1); padding:8px; text-align:left; }}
    th {{ color:#64748b; font-size:.68rem; text-transform:uppercase; }}
    .badge {{ border-radius:999px; font-size:.68rem; padding:2px 7px; }}
    .badge-apply {{ background:rgba(16,185,129,.18); color:#6ee7b7; }}
    .badge-review {{ background:rgba(245,158,11,.18); color:#fcd34d; }}
    .badge-other {{ background:rgba(148,163,184,.12); color:#94a3b8; }}
    .file-btn {{ border:none; border-radius:6px; padding:4px 8px; font-size:.73rem; margin-right:4px; cursor:pointer; }}
    .btn-apply {{ background:rgba(16,185,129,.2); color:#a7f3d0; }}
    .btn-draft {{ background:rgba(56,189,248,.2); color:#7dd3fc; }}
    .btn-resume {{ background:rgba(52,211,153,.2); color:#86efac; }}
    .empty-state {{ color:var(--muted); text-align:center; padding:20px; }}
    .toast {{ position:fixed; right:20px; bottom:20px; background:#1e293b; border:1px solid var(--border); border-radius:10px; padding:10px 14px; opacity:0; transform:translateY(60px); transition:all .25s; }}
    .toast.show {{ opacity:1; transform:translateY(0); }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Job Apply Dashboard</h1>
    <p class="sub">Single-place job view with per-row apply links and reusable answer memory.</p>

    <div class="panel">
      <button id="run-btn" class="run-btn" onclick="runPipeline()">Run Pipeline and Score Jobs</button>
      <div class="run-output" id="pipeline-out">Ready.</div>
            <details class="raw-output-wrap" id="pipeline-raw-wrap">
                <summary>View full raw output</summary>
                <pre class="raw-output" id="pipeline-raw">No raw output yet.</pre>
            </details>
    </div>

    <div class="panel">
      <div class="jobs-head">
        <h2 style="margin:0;font-size:1rem">Ranked Jobs</h2>
        <div style="display:flex;align-items:center;gap:8px">
          <label style="font-size:.75rem;color:var(--muted)">Per page</label>
          <select id="page-size-select" onchange="changePageSize()" style="background:#0f172a;color:var(--text);border:1px solid var(--border);border-radius:8px;padding:4px 8px;font-size:.75rem;cursor:pointer">
            <option value="25">25</option>
            <option value="50">50</option>
            <option value="100">100</option>
            <option value="0">All</option>
          </select>
          <button class="refresh-btn" onclick="loadJobs()">Refresh</button>
        </div>
      </div>
      <div id="stats-row" class="stats-row" style="display:none"></div>
      <div id="jobs-container" class="empty-state">Loading jobs...</div>
      <div id="pagination-row" style="display:none;justify-content:center;align-items:center;gap:6px;padding:12px 0"></div>
    </div>
  </div>
  <div id="toast" class="toast"></div>

  <script>
    function q(id) {{ return document.getElementById(id); }}
    function toast(msg, ok) {{
      var t = q('toast');
      t.textContent = (ok ? '[OK] ' : '[WARN] ') + msg;
      t.className = 'toast show';
      setTimeout(function() {{ t.className = 'toast'; }}, 2500);
    }}

    function esc(v) {{
      return String(v || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\"/g,'&quot;').replace(/'/g,'&#39;');
    }}

        async function openJob(url, role, company) {{
      if (!url) {{ toast('No apply URL for this job', false); return; }}
            var r = await fetch('/api/open-job?url=' + encodeURIComponent(url) + '&role=' + encodeURIComponent(role || '') + '&company=' + encodeURIComponent(company || ''), {{ method: 'POST' }});
      var d = await r.json();
      toast(d.ok ? 'Opened job posting' : (d.message || 'Could not open URL'), d.ok);
    }}

    async function openFile(path) {{
      if (!path) {{ toast('File not available', false); return; }}
      var r = await fetch('/api/open-file?path=' + encodeURIComponent(path), {{ method: 'POST' }});
      var d = await r.json();
      toast(d.ok ? 'Opened file' : d.message, d.ok);
    }}

    async function runPipeline() {{
      var btn = q('run-btn');
      var out = q('pipeline-out');
            var rawWrap = q('pipeline-raw-wrap');
      btn.disabled = true;
      btn.textContent = 'Running...';
      out.textContent = 'Scoring jobs...';
            setRawOutput('Waiting for pipeline output...');
            if (rawWrap) rawWrap.open = false;
      var r = await fetch('/api/run-pipeline', {{ method: 'POST' }});
      var d = await r.json();
      btn.disabled = false;
      btn.textContent = 'Run Pipeline and Score Jobs';
      if (d.ok) {{
                out.textContent = summarizePipelineOutput(d.stdout);
                setRawOutput(d.stdout || 'No stdout content returned.');
        loadJobs();
        toast('Pipeline complete', true);
      }} else {{
                out.textContent = 'Error: ' + summarizePipelineOutput(d.stderr || d.stdout || 'Unknown');
                setRawOutput((d.stderr || d.stdout || 'Unknown error output') + '\\n');
                if (rawWrap) rawWrap.open = true;
        toast('Pipeline failed', false);
      }}
    }}

        function setRawOutput(raw) {{
            var rawEl = q('pipeline-raw');
            if (!rawEl) return;
            var text = String(raw || '').trim();
            if (!text) {{
                rawEl.textContent = 'No raw output yet.';
                return;
            }}
            if (text.length > 50000) {{
                rawEl.textContent = text.slice(0, 50000) + '\\n... (truncated)';
                return;
            }}
            rawEl.textContent = text;
        }}

        function summarizePipelineOutput(raw) {{
            var text = String(raw || '').trim();
            if (!text) return 'Pipeline finished successfully.';

            try {{
                var obj = JSON.parse(text);
                var lines = [];
                if (obj.generated_on) lines.push('generated_on: ' + obj.generated_on);
                if (obj.manifest) lines.push('manifest: ' + obj.manifest);
                if (obj.accepted_records != null) lines.push('accepted_records: ' + obj.accepted_records);
                if (obj.rejected_records != null) lines.push('rejected_records: ' + obj.rejected_records);
                if (obj.tailored_resumes_written != null) lines.push('tailored_resumes_written: ' + obj.tailored_resumes_written);
                if (obj.draft_files_written != null) lines.push('draft_files_written: ' + obj.draft_files_written);
                if (obj.action_breakdown && typeof obj.action_breakdown === 'object') {{
                    lines.push('action_breakdown: ' + JSON.stringify(obj.action_breakdown));
                }}
                if (obj.status_breakdown && typeof obj.status_breakdown === 'object') {{
                    lines.push('status_breakdown: ' + JSON.stringify(obj.status_breakdown));
                }}
                if (obj.top_recommendations && Array.isArray(obj.top_recommendations)) {{
                    lines.push('top_recommendations: ' + obj.top_recommendations.length + ' jobs');
                }}
                if (lines.length) return lines.join('\\n');
            }} catch (e) {{
                // Not JSON output; fall back to truncated text.
            }}

            if (text.length > 1000) {{
                return text.slice(0, 1000) + '\\n... (truncated)';
            }}
            return text;
        }}

    function bindButtons() {{
      var applyButtons = document.querySelectorAll('button[data-apply]');
      for (var i = 0; i < applyButtons.length; i++) {{
        applyButtons[i].addEventListener('click', function(ev) {{
                    openJob(
                        ev.currentTarget.getAttribute('data-apply') || '',
                        ev.currentTarget.getAttribute('data-role') || '',
                        ev.currentTarget.getAttribute('data-company') || ''
                    );
        }});
      }}
      var fileButtons = document.querySelectorAll('button[data-file]');
      for (var j = 0; j < fileButtons.length; j++) {{
        fileButtons[j].addEventListener('click', function(ev) {{
          openFile(ev.currentTarget.getAttribute('data-file') || '');
        }});
      }}
    }}

    function badge(action) {{
      if (action === 'apply_now') return '<span class="badge badge-apply">Apply Now</span>';
      if (action === 'review_fast') return '<span class="badge badge-review">Review</span>';
      return '<span class="badge badge-other">' + esc(action) + '</span>';
    }}

    function match(score) {{
      if (score == null) return '-';
      return esc(score) + '%';
    }}

    var _allJobs = [];
    var _currentPage = 1;

    function getPageSize() {{
      var sel = q('page-size-select');
      return sel ? parseInt(sel.value, 10) : 25;
    }}

    function changePageSize() {{
      _currentPage = 1;
      renderJobsPage();
    }}

    function renderJobsPage() {{
      var c = q('jobs-container');
      var pr = q('pagination-row');
      var ps = getPageSize();
      var jobs = ps <= 0 ? _allJobs : _allJobs.slice((_currentPage - 1) * ps, _currentPage * ps);
      var html = '<table><thead><tr><th>#</th><th>Company</th><th>Role</th><th>Score</th><th>Action</th><th>Apply</th><th>JD Match</th><th>Files</th></tr></thead><tbody>';
      for (var i = 0; i < jobs.length; i++) {{
        var j = jobs[i];
        html += '<tr>';
        html += '<td>' + esc(j.rank) + '</td>';
        html += '<td><b>' + esc(j.company) + '</b></td>';
        html += '<td>' + esc(j.role) + '</td>';
        html += '<td>' + esc(j.score) + '</td>';
        html += '<td>' + badge(j.action) + '</td>';
        html += j.apply_url ? '<td><button class="file-btn btn-apply" data-apply="' + esc(j.apply_url) + '" data-role="' + esc(j.role) + '" data-company="' + esc(j.company) + '">Apply Now</button></td>' : '<td><button class="file-btn btn-apply" disabled>Apply Now</button></td>';
        html += '<td>' + match(j.keyword_match_score) + '</td>';
        html += '<td>';
        html += j.draft_file ? '<button class="file-btn btn-draft" data-file="' + esc(j.draft_file) + '">Draft</button>' : '<button class="file-btn btn-draft" disabled>Draft</button>';
        html += j.resume_file ? '<button class="file-btn btn-resume" data-file="' + esc(j.resume_file) + '">Resume</button>' : '<button class="file-btn btn-resume" disabled>Resume</button>';
        html += '</td></tr>';
      }}
      html += '</tbody></table>';
      c.innerHTML = html;
      bindButtons();
      if (ps <= 0 || _allJobs.length <= ps) {{
        pr.style.display = 'none';
      }} else {{
        var totalPages = Math.ceil(_allJobs.length / ps);
        var phtml = '<span style="font-size:.78rem;color:var(--muted)">' + ((_currentPage-1)*ps+1) + '\u2013' + Math.min(_currentPage*ps,_allJobs.length) + ' of ' + _allJobs.length + '</span>';
        phtml += '<button class="refresh-btn" onclick="goPage(' + (_currentPage-1) + ')"' + (_currentPage<=1?' disabled':'') + '>&#8592; Prev</button>';
        for (var p = 1; p <= totalPages; p++) {{
          phtml += '<button class="refresh-btn" onclick="goPage(' + p + ')" style="' + (p===_currentPage?'background:var(--accent);color:#042433;':'') + '">' + p + '</button>';
        }}
        phtml += '<button class="refresh-btn" onclick="goPage(' + (_currentPage+1) + ')"' + (_currentPage>=totalPages?' disabled':'') + '>Next &#8594;</button>';
        pr.innerHTML = phtml;
        pr.style.display = 'flex';
      }}
    }}

    function goPage(p) {{
      var ps = getPageSize();
      var totalPages = ps <= 0 ? 1 : Math.ceil(_allJobs.length / ps);
      _currentPage = Math.max(1, Math.min(p, totalPages));
      renderJobsPage();
      q('jobs-container').scrollIntoView({{behavior:'smooth',block:'start'}});
    }}

    async function loadJobs() {{
      var c = q('jobs-container');
      var sr = q('stats-row');
      var pr = q('pagination-row');
      c.innerHTML = '<div class="empty-state">Loading jobs...</div>';
      sr.style.display = 'none';
      if (pr) pr.style.display = 'none';
      var r = await fetch('/api/latest-jobs');
      var d = await r.json();
      if (!d.ok || !d.manifest || !d.manifest.jobs || !d.manifest.jobs.length) {{
        c.innerHTML = '<div class="empty-state">' + esc(d.message || 'No jobs found yet') + '</div>';
        return;
      }}
      _allJobs = d.manifest.jobs;
      _currentPage = 1;
      var applyNow = _allJobs.filter(function(x) {{ return x.action === 'apply_now'; }}).length;
      var reviewFast = _allJobs.filter(function(x) {{ return x.action === 'review_fast'; }}).length;
      var resumes = _allJobs.filter(function(x) {{ return !!x.resume_file; }}).length;
      sr.innerHTML = '<div class="stat-chip">Last run <b>' + esc(d.manifest.generated_on || '') + '</b></div>' +
        '<div class="stat-chip"><b style="color:var(--green)">' + applyNow + '</b> Apply Now</div>' +
        '<div class="stat-chip"><b style="color:var(--accent)">' + reviewFast + '</b> Review Fast</div>' +
        '<div class="stat-chip"><b>' + resumes + '</b> Tailored Resumes</div>' +
        '<div class="stat-chip"><b>' + _allJobs.length + '</b> Total</div>';
      sr.style.display = 'flex';
      renderJobsPage();
    }}

    loadJobs();
  </script>
</body>
</html>"""


def main() -> None:
    args = build_parser().parse_args()
    config = load_ui_config(Path(args.config))
    handler = make_handler(config)
    server = ThreadingHTTPServer((args.host, args.port), handler)

    url = f"http://{args.host}:{args.port}"
    print(f"UI running at {url}")
    print("This is an assisted mode: review forms and click final submit manually.")

    if args.open_browser:
        webbrowser.open_new_tab(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
