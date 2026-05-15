from __future__ import annotations

import re
from datetime import date
from pathlib import Path


def build_application_draft(record: dict[str, object], generated_on: date | None = None) -> str:
    run_date = generated_on or date.today()
    company = str(record.get("company", "Unknown Company"))
    role = str(record.get("role", "Unknown Role"))
    action = str(record.get("action", "review_fast"))
    score = int(record.get("score", 0))
    reasons = [str(item) for item in record.get("reasons", [])]
    notes = str(record.get("notes", "")).strip()

    highlights = "\n".join(f"- {reason}" for reason in reasons) if reasons else "- Strong potential match"
    note_text = notes if notes else "No additional notes provided"

    return "\n".join(
        [
            f"# Application Draft: {role} at {company}",
            "",
            f"Generated on: {run_date.isoformat()}",
            f"Pipeline action: {action}",
            f"Pipeline score: {score}",
            "",
            "## Why This Role",
            highlights,
            "",
            "## Tailored Intro (Editable)",
            (
                f"I am excited to apply for the {role} role at {company}. "
                "My background in building reliable data pipelines and analytics platforms "
                "aligns with the technical requirements in this opportunity."
            ),
            "",
            "## Talking Points for Resume/Interview",
            "- Delivered production ETL/ELT pipelines with Python and SQL.",
            "- Improved data quality and reliability with orchestration and monitoring.",
            "- Collaborated with analytics and platform teams to ship business-critical datasets.",
            "",
            "## Source Notes",
            note_text,
            "",
            "## Submit Checklist",
            "- Update resume bullets to mirror this job description.",
            "- Keep visa/work authorization statement consistent and clear.",
            "- Submit application and log confirmation/reference number.",
        ]
    )


def write_application_drafts(records: list[dict[str, object]], output_dir: Path, generated_on: date | None = None) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    created_files: list[Path] = []

    for index, record in enumerate(records, start=1):
        company = str(record.get("company", "unknown-company"))
        role = str(record.get("role", "unknown-role"))
        filename = f"{index:02d}_{_slugify(company)}_{_slugify(role)}.md"
        path = output_dir / filename
        path.write_text(build_application_draft(record, generated_on=generated_on), encoding="utf-8")
        created_files.append(path)

    return created_files


def _slugify(value: str) -> str:
    compact = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return compact or "item"