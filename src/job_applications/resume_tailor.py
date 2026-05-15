"""Resume tailoring engine.

Given a candidate's structured base resume (JSON) and the plain-text of a
job description, this module:

1. Extracts known technology keywords from the JD.
2. For every job entry in the base resume, injects only those keywords that
   were publicly available **on or before the job's end year** — preventing
   historically impossible claims (e.g. listing Delta Lake (2019) for a role
   that ended in 2017).
3. Reorders the skills section so JD-matched skills appear first.
4. Appends JD buzzwords to the professional summary.
5. Renders the tailored resume as formatted Markdown, ready to copy-paste or
   convert to PDF.

Edge-case rules enforced
-------------------------
* A technology is only injected into a role if  release_year ≤ role.end_year.
* "Present" / "current" / 0 end years resolve to the current calendar year.
* Skills already listed in the role's existing_technologies are not duplicated.
* The keyword-match score (0–100 %) reflects only skills the candidate
  credibly owns, giving a realistic signal of how well the resume fits the JD.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .tech_dates import TECH_RELEASE_YEARS, normalize_skill, skill_available_at

CURRENT_YEAR: int = date.today().year

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ExperienceEntry:
    company: str
    title: str
    start_year: int
    end_year: int           # 0 means "present"
    location: str
    bullets: list[str]
    existing_technologies: list[str] = field(default_factory=list)

    @property
    def resolved_end_year(self) -> int:
        return CURRENT_YEAR if self.end_year == 0 else self.end_year


@dataclass
class EducationEntry:
    institution: str
    degree: str
    field_of_study: str
    year: int


@dataclass
class BaseResume:
    name: str
    email: str
    phone: str
    linkedin: str
    location: str
    summary: str
    skills: list[str]
    experience: list[ExperienceEntry]
    education: list[EducationEntry]
    certifications: list[str]


@dataclass
class TailoredExperienceEntry:
    company: str
    title: str
    start_year: int
    end_year: int
    location: str
    bullets: list[str]
    injected_technologies: list[str]   # new skills from JD, date-gated

    @property
    def resolved_end_year(self) -> int:
        return CURRENT_YEAR if self.end_year == 0 else self.end_year


@dataclass
class TailoredResume:
    base: BaseResume
    job_title: str
    company: str
    jd_keywords: list[str]
    matched_keywords: list[str]        # JD keywords the candidate credibly owns
    keyword_match_score: int           # matched / total  as 0-100 integer
    tailored_summary: str
    ordered_skills: list[str]
    experience: list[TailoredExperienceEntry]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_base_resume(path: str) -> BaseResume:
    """Load a structured base resume from a JSON file."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    experience: list[ExperienceEntry] = []
    for e in data.get("experience", []):
        raw_end = e.get("end_year", 0)
        end_year = 0 if str(raw_end).strip().lower() in {"present", "current", "0", ""} else int(raw_end)
        experience.append(
            ExperienceEntry(
                company=e.get("company", ""),
                title=e.get("title", ""),
                start_year=int(e.get("start_year", 2000)),
                end_year=end_year,
                location=e.get("location", ""),
                bullets=e.get("bullets", []),
                existing_technologies=[t.lower() for t in e.get("existing_technologies", [])],
            )
        )

    education: list[EducationEntry] = []
    for ed in data.get("education", []):
        education.append(
            EducationEntry(
                institution=ed.get("institution", ""),
                degree=ed.get("degree", ""),
                field_of_study=ed.get("field", ""),
                year=int(ed.get("year", 0)),
            )
        )

    return BaseResume(
        name=data.get("name", ""),
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        linkedin=data.get("linkedin", ""),
        location=data.get("location", ""),
        summary=data.get("summary", ""),
        skills=[s.strip() for s in data.get("skills", [])],
        experience=experience,
        education=education,
        certifications=data.get("certifications", []),
    )


# ---------------------------------------------------------------------------
# Keyword extraction
# ---------------------------------------------------------------------------

def extract_jd_keywords(jd_text: str) -> list[str]:
    """Return known technology keywords found in *jd_text*.

    Multi-word phrases (e.g. "azure data factory") are matched before their
    constituent single words so the longest match wins.
    """
    text_lower = jd_text.lower()
    # Longest phrases first so multi-word entries are consumed before single words
    candidates = sorted(TECH_RELEASE_YEARS.keys(), key=len, reverse=True)

    found: list[str] = []
    consumed: list[tuple[int, int]] = []  # (start, end) of already-matched spans

    for skill in candidates:
        pattern = re.compile(r"\b" + re.escape(skill) + r"\b")
        for match in pattern.finditer(text_lower):
            s, e = match.start(), match.end()
            # Skip if overlaps with an already consumed span
            if any(cs <= s < ce or cs < e <= ce for cs, ce in consumed):
                continue
            found.append(skill)
            consumed.append((s, e))
            break  # count each skill name once

    # Stable deduplicate
    seen: set[str] = set()
    result: list[str] = []
    for kw in found:
        if kw not in seen:
            seen.add(kw)
            result.append(kw)
    return result


# ---------------------------------------------------------------------------
# Core tailoring helpers
# ---------------------------------------------------------------------------

def _new_skills_for_entry(entry: ExperienceEntry, jd_keywords: list[str]) -> list[str]:
    """Return JD keywords that:
    * were publicly available by the job's end year, AND
    * are not already listed in existing_technologies for that entry.
    """
    existing = set(entry.existing_technologies)  # already lowercased on load
    result: list[str] = []
    for kw in jd_keywords:
        if normalize_skill(kw) in existing:
            continue
        if skill_available_at(kw, entry.resolved_end_year):
            result.append(kw)
    return result


def _build_tailored_summary(base_summary: str, top_keywords: list[str]) -> str:
    """Weave the top JD keywords into the professional summary."""
    if not top_keywords:
        return base_summary
    kw_phrase = ", ".join(top_keywords[:7])
    sentence = base_summary.rstrip(". ")
    return f"{sentence}, with hands-on expertise in {kw_phrase}."


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def tailor_resume(
    base: BaseResume,
    jd_text: str,
    job_title: str,
    company: str,
) -> TailoredResume:
    """Produce a *TailoredResume* by aligning *base* against *jd_text*.

    The function never fabricates experience.  It only:
    * surfaces existing skills in JD-priority order,
    * appends date-gated technologies to each job's tech stack line, and
    * enhances the summary with matching buzzwords.
    """
    jd_keywords = extract_jd_keywords(jd_text)

    # Collect all skills the candidate can credibly claim (skills + each job's techs)
    candidate_skills_lower: set[str] = {normalize_skill(s) for s in base.skills}
    for exp in base.experience:
        candidate_skills_lower.update(exp.existing_technologies)

    # JD keywords the candidate already owns
    matched = [kw for kw in jd_keywords if normalize_skill(kw) in candidate_skills_lower]
    score = round(len(matched) / len(jd_keywords) * 100) if jd_keywords else 0

    # Build tailored experience entries (inject new date-gated JD skills)
    tailored_experience: list[TailoredExperienceEntry] = []
    for exp in base.experience:
        injected = _new_skills_for_entry(exp, jd_keywords)
        tailored_experience.append(
            TailoredExperienceEntry(
                company=exp.company,
                title=exp.title,
                start_year=exp.start_year,
                end_year=exp.end_year,
                location=exp.location,
                bullets=list(exp.bullets),
                injected_technologies=injected,
            )
        )

    # Reorder skills: JD-matched ones first, then the rest
    ordered_skills: list[str] = []
    seen_lower: set[str] = set()
    for kw in jd_keywords:
        kw_l = normalize_skill(kw)
        if kw_l in candidate_skills_lower and kw_l not in seen_lower:
            # Prefer the casing/name from the candidate's own skill list
            canonical_from_base = next(
                (s for s in base.skills if normalize_skill(s) == kw_l),
                kw,
            )
            ordered_skills.append(canonical_from_base)
            seen_lower.add(kw_l)
    for s in base.skills:
        s_l = normalize_skill(s)
        if s_l not in seen_lower:
            ordered_skills.append(s)
            seen_lower.add(s_l)

    tailored_summary = _build_tailored_summary(base.summary, jd_keywords[:8])

    return TailoredResume(
        base=base,
        job_title=job_title,
        company=company,
        jd_keywords=jd_keywords,
        matched_keywords=matched,
        keyword_match_score=score,
        tailored_summary=tailored_summary,
        ordered_skills=ordered_skills,
        experience=tailored_experience,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _year_range(start: int, end: int) -> str:
    end_str = "Present" if end == 0 else str(end)
    return f"{start} – {end_str}"


def render_resume_markdown(tailored: TailoredResume) -> str:
    """Render the tailored resume as a Markdown string."""
    b = tailored.base
    lines: list[str] = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines.append(f"# {b.name}")
    contact = " | ".join(p for p in [b.email, b.phone, b.linkedin, b.location] if p)
    lines.append(contact)
    lines.append("")

    # ── Summary ───────────────────────────────────────────────────────────────
    lines.append("## Summary")
    lines.append(tailored.tailored_summary)
    lines.append("")

    # ── Skills ────────────────────────────────────────────────────────────────
    lines.append("## Skills")
    lines.append(", ".join(tailored.ordered_skills))
    lines.append("")

    # ── Experience ────────────────────────────────────────────────────────────
    lines.append("## Experience")
    for exp in tailored.experience:
        date_range = _year_range(exp.start_year, exp.end_year)
        loc_date = " | ".join(p for p in [exp.location, date_range] if p)
        lines.append(f"### {exp.title} — {exp.company}")
        lines.append(f"*{loc_date}*")
        lines.append("")
        for bullet in exp.bullets:
            lines.append(f"- {bullet}")
        if exp.injected_technologies:
            lines.append(f"- **Tech Stack:** {', '.join(exp.injected_technologies)}")
        lines.append("")

    # ── Education ─────────────────────────────────────────────────────────────
    if b.education:
        lines.append("## Education")
        for ed in b.education:
            yr = f" ({ed.year})" if ed.year else ""
            lines.append(f"**{ed.degree} in {ed.field_of_study}** — {ed.institution}{yr}")
        lines.append("")

    # ── Certifications ────────────────────────────────────────────────────────
    if b.certifications:
        lines.append("## Certifications")
        for cert in b.certifications:
            lines.append(f"- {cert}")
        lines.append("")

    # ── Footer ────────────────────────────────────────────────────────────────
    lines.append("---")
    lines.append(
        f"*Tailored for: {tailored.job_title} at {tailored.company} "
        f"| JD keyword match: {tailored.keyword_match_score}% "
        f"({len(tailored.matched_keywords)}/{len(tailored.jd_keywords)} keywords)*"
    )

    return "\n".join(lines)


def write_tailored_resume(tailored: TailoredResume, output_path: str) -> None:
    """Write the rendered Markdown resume to *output_path*."""
    content = render_resume_markdown(tailored)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
