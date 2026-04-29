from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ApplicationRecord:
    company: str
    role: str
    status: str
    notes: str = ""
    apply_url: str = ""


@dataclass(frozen=True)
class PipelineSummary:
    total_records: int
    accepted_records: int
    rejected_records: int
    status_breakdown: dict[str, int]
    action_breakdown: dict[str, int]
    top_recommendations: list[dict[str, object]]


@dataclass(frozen=True)
class CandidateProfile:
    target_titles: list[str]
    required_keywords: list[str]
    preferred_keywords: list[str]
    preferred_locations: list[str]
    require_visa_support: bool = True


def default_profile() -> CandidateProfile:
    return CandidateProfile(
        target_titles=[
            "data engineer",
            "senior data engineer",
            "analytics engineer",
            "data platform engineer",
            "etl engineer",
        ],
        required_keywords=["python", "sql", "etl"],
        preferred_keywords=[
            "airflow",
            "dbt",
            "spark",
            "kafka",
            "snowflake",
            "databricks",
            "aws",
            "gcp",
            "azure",
        ],
        preferred_locations=["remote", "usa", "united states"],
        require_visa_support=True,
    )


def _normalize_record(raw_record: dict[str, str]) -> ApplicationRecord | None:
    company = raw_record.get("company", "").strip()
    role = raw_record.get("role", "").strip()
    status = raw_record.get("status", "").strip().lower()
    notes = raw_record.get("notes", "").strip()
    apply_url = raw_record.get("apply_url", "").strip()

    if not company or not role or not status:
        return None

    return ApplicationRecord(company=company, role=role, status=status, notes=notes, apply_url=apply_url)


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(term in text for term in terms)


def _score_record(record: ApplicationRecord, profile: CandidateProfile) -> tuple[int, str, list[str]]:
    text = f"{record.company} {record.role} {record.notes}".lower()
    reasons: list[str] = []

    negative_visa_signals = [
        "no sponsorship",
        "unable to sponsor",
        "us citizen",
        "usc only",
        "green card only",
        "no visa",
    ]
    positive_visa_signals = [
        "h1b",
        "visa transfer",
        "sponsorship available",
        "sponsor",
        "opt",
    ]

    if profile.require_visa_support and _contains_any(text, negative_visa_signals):
        reasons.append("Rejected: role appears to disallow visa sponsorship")
        return 0, "skip", reasons

    score = 0

    role_text = record.role.lower()
    if _contains_any(role_text, profile.target_titles):
        score += 35
        reasons.append("Strong role-title match")

    required_hits = sum(1 for keyword in profile.required_keywords if keyword in text)
    if required_hits:
        score += min(required_hits * 12, 36)
        reasons.append(f"Matched required keywords: {required_hits}/{len(profile.required_keywords)}")

    preferred_hits = sum(1 for keyword in profile.preferred_keywords if keyword in text)
    if preferred_hits:
        score += min(preferred_hits * 4, 20)
        reasons.append(f"Matched preferred keywords: {preferred_hits}")

    if _contains_any(text, profile.preferred_locations):
        score += 8
        reasons.append("Preferred location signal")

    if profile.require_visa_support and _contains_any(text, positive_visa_signals):
        score += 12
        reasons.append("Positive visa-support signal")

    if score >= 70:
        return score, "apply_now", reasons
    if score >= 45:
        return score, "review_fast", reasons
    return score, "backlog", reasons


def run_pipeline(
    raw_records: Iterable[dict[str, str]],
    profile: CandidateProfile | None = None,
    top_k: int = 10,
) -> PipelineSummary:
    active_profile = profile or default_profile()
    accepted_records = 0
    rejected_records = 0
    status_breakdown: dict[str, int] = {}
    action_breakdown: dict[str, int] = {}
    scored_records: list[dict[str, object]] = []

    for raw_record in raw_records:
        record = _normalize_record(raw_record)
        if record is None:
            rejected_records += 1
            continue

        accepted_records += 1
        status_breakdown[record.status] = status_breakdown.get(record.status, 0) + 1

        score, action, reasons = _score_record(record, active_profile)
        action_breakdown[action] = action_breakdown.get(action, 0) + 1
        scored_records.append(
            {
                "company": record.company,
                "role": record.role,
                "status": record.status,
                "score": score,
                "action": action,
                "reasons": reasons,
                "notes": record.notes,
                "apply_url": record.apply_url,
            }
        )

    scored_records.sort(key=lambda item: int(item["score"]), reverse=True)

    return PipelineSummary(
        total_records=accepted_records + rejected_records,
        accepted_records=accepted_records,
        rejected_records=rejected_records,
        status_breakdown=status_breakdown,
        action_breakdown=action_breakdown,
        top_recommendations=scored_records[: max(top_k, 0)],
    )
