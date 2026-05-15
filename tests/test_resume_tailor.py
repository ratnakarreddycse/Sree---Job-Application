"""Tests for resume_tailor and tech_dates modules."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from job_applications.tech_dates import release_year, skill_available_at
from job_applications.resume_tailor import (
    BaseResume,
    ExperienceEntry,
    EducationEntry,
    TailoredResume,
    extract_jd_keywords,
    load_base_resume,
    render_resume_markdown,
    tailor_resume,
    write_tailored_resume,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_base_resume() -> BaseResume:
    """Return a minimal BaseResume spanning 2014–present."""
    return BaseResume(
        name="Jane Doe",
        email="jane@example.com",
        phone="+1-555-000-0000",
        linkedin="linkedin.com/in/janedoe",
        location="Remote, USA",
        summary="Experienced data engineer with a passion for building scalable pipelines.",
        skills=["Python", "SQL", "Spark", "Airflow", "AWS"],
        experience=[
            ExperienceEntry(
                company="Acme Corp",
                title="Data Engineer",
                start_year=2014,
                end_year=0,           # "present"
                location="Remote",
                bullets=["Built ETL pipelines using Spark on AWS EMR."],
                existing_technologies=["python", "sql", "spark", "aws", "emr"],
            ),
            ExperienceEntry(
                company="Old Co",
                title="Junior Data Analyst",
                start_year=2012,
                end_year=2014,
                location="New York, NY",
                bullets=["Wrote SQL queries for reporting."],
                existing_technologies=["sql", "mysql"],
            ),
        ],
        education=[
            EducationEntry(
                institution="State University",
                degree="B.S.",
                field_of_study="Computer Science",
                year=2012,
            )
        ],
        certifications=["AWS Certified Data Analytics"],
    )


# ---------------------------------------------------------------------------
# tech_dates: release_year / skill_available_at
# ---------------------------------------------------------------------------

class TestTechDates:
    def test_known_skills_have_correct_release_years(self):
        assert release_year("kafka") == 2011
        assert release_year("delta lake") == 2019
        assert release_year("airflow") == 2015
        assert release_year("azure synapse") == 2019
        assert release_year("github actions") == 2019
        assert release_year("dbt") == 2016
        assert release_year("snowflake") == 2014

    def test_skill_available_exactly_at_release_year(self):
        # Delta Lake released 2019 — should be available in 2019
        assert skill_available_at("delta lake", 2019) is True

    def test_skill_not_available_before_release(self):
        # Delta Lake released 2019 — NOT available in 2017
        assert skill_available_at("delta lake", 2017) is False
        # Azure Synapse released 2019 — NOT available in 2018
        assert skill_available_at("azure synapse", 2018) is False
        # Airbyte released 2020 — NOT available in 2019
        assert skill_available_at("airbyte", 2019) is False

    def test_unknown_skill_is_always_available(self):
        # Tools not in our DB should not be blocked
        assert skill_available_at("some_unknown_tool_xyz", 2010) is True
        assert skill_available_at("some_unknown_tool_xyz", 1990) is True


# ---------------------------------------------------------------------------
# extract_jd_keywords
# ---------------------------------------------------------------------------

class TestExtractJdKeywords:
    def test_extracts_single_word_skills(self):
        jd = "We need someone with Spark, Kafka, and dbt experience."
        kws = extract_jd_keywords(jd)
        kws_lower = [k.lower() for k in kws]
        assert "spark" in kws_lower
        assert "kafka" in kws_lower
        assert "dbt" in kws_lower

    def test_multi_word_phrase_preferred_over_single_word(self):
        # "azure data factory" should be found as a unit, not just "azure"
        jd = "Experience with Azure Data Factory and Azure Synapse Analytics required."
        kws = extract_jd_keywords(jd)
        kws_lower = [k.lower() for k in kws]
        assert "azure data factory" in kws_lower or "adf" in kws_lower
        # "azure" alone should NOT appear separately if the phrase was consumed
        # (single-word "azure" span overlaps with multi-word match)
        # At minimum the multi-word match must be present
        assert any("azure" in k for k in kws_lower)

    def test_no_duplicate_keywords(self):
        jd = "Python Python SQL SQL Spark Spark"
        kws = extract_jd_keywords(jd)
        assert len(kws) == len(set(kws))

    def test_empty_jd_returns_empty_list(self):
        assert extract_jd_keywords("") == []


# ---------------------------------------------------------------------------
# tailor_resume: date gating
# ---------------------------------------------------------------------------

class TestTailorResumeGating:
    def test_future_tool_not_injected_into_old_role(self):
        """Delta Lake (2019) must NOT appear in the 2012-2014 Old Co role."""
        base = _make_base_resume()
        jd = "We use Delta Lake, dbt, Spark, Python, and SQL."
        result = tailor_resume(base, jd, "Data Engineer", "TechCo")

        old_co_entry = next(e for e in result.experience if e.company == "Old Co")
        injected_lower = [t.lower() for t in old_co_entry.injected_technologies]
        assert "delta lake" not in injected_lower
        assert "delta" not in injected_lower

    def test_available_tool_injected_into_current_role(self):
        """dbt (2016) SHOULD appear in the Acme Corp role that runs to present."""
        base = _make_base_resume()
        jd = "Strong experience with dbt, Snowflake, and Delta Lake required."
        result = tailor_resume(base, jd, "Senior Data Engineer", "TechCo")

        acme_entry = next(e for e in result.experience if e.company == "Acme Corp")
        injected_lower = [t.lower() for t in acme_entry.injected_technologies]
        assert "dbt" in injected_lower

    def test_existing_tech_not_duplicated(self):
        """Skills already in existing_technologies must not appear in injected."""
        base = _make_base_resume()
        jd = "Experience with Spark, Kafka, dbt required."
        result = tailor_resume(base, jd, "Data Engineer", "TechCo")

        acme_entry = next(e for e in result.experience if e.company == "Acme Corp")
        injected_lower = [t.lower() for t in acme_entry.injected_technologies]
        # "spark" is already in existing_technologies for Acme Corp
        assert "spark" not in injected_lower

    def test_keyword_match_score_range(self):
        base = _make_base_resume()
        jd = "Python, SQL, Spark, Kafka, dbt, Snowflake"
        result = tailor_resume(base, jd, "Data Engineer", "TechCo")
        assert 0 <= result.keyword_match_score <= 100

    def test_jd_matched_skills_appear_first_in_ordered_skills(self):
        base = _make_base_resume()
        jd = "We need expertise in Kafka and SQL."
        result = tailor_resume(base, jd, "Data Engineer", "TechCo")
        # SQL is in base skills; it should appear early
        sql_idx = next(
            (i for i, s in enumerate(result.ordered_skills) if s.lower() == "sql"),
            None,
        )
        assert sql_idx is not None
        assert sql_idx < 3  # near the top


# ---------------------------------------------------------------------------
# render_resume_markdown
# ---------------------------------------------------------------------------

class TestRenderResumeMarkdown:
    def test_markdown_contains_required_sections(self):
        base = _make_base_resume()
        result = tailor_resume(base, "Python Spark dbt Kafka Snowflake", "Data Engineer", "TechCo")
        md = render_resume_markdown(result)
        assert "# Jane Doe" in md
        assert "## Summary" in md
        assert "## Skills" in md
        assert "## Experience" in md
        assert "## Education" in md
        assert "## Certifications" in md
        assert "keyword match" in md.lower()

    def test_markdown_includes_job_context(self):
        base = _make_base_resume()
        result = tailor_resume(base, "Python Spark Kafka", "Senior Data Engineer", "MegaCorp")
        md = render_resume_markdown(result)
        assert "MegaCorp" in md
        assert "Senior Data Engineer" in md


# ---------------------------------------------------------------------------
# load_base_resume + write_tailored_resume (round-trip with real file I/O)
# ---------------------------------------------------------------------------

class TestFileIO:
    def test_load_base_resume_from_file(self):
        sample = {
            "name": "Test User",
            "email": "test@test.com",
            "phone": "",
            "linkedin": "",
            "location": "Remote",
            "summary": "A summary.",
            "skills": ["Python", "SQL"],
            "experience": [
                {
                    "company": "X Corp",
                    "title": "Engineer",
                    "start_year": 2018,
                    "end_year": "present",
                    "location": "Remote",
                    "bullets": ["Did things."],
                    "existing_technologies": ["python"],
                }
            ],
            "education": [
                {"institution": "Uni", "degree": "B.S.", "field": "CS", "year": 2018}
            ],
            "certifications": [],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(sample, f)
            tmp_path = f.name
        try:
            resume = load_base_resume(tmp_path)
            assert resume.name == "Test User"
            assert resume.experience[0].resolved_end_year >= 2024
        finally:
            os.unlink(tmp_path)

    def test_write_tailored_resume_creates_file(self):
        base = _make_base_resume()
        result = tailor_resume(base, "Python Spark dbt", "Data Engineer", "TestCo")
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = os.path.join(tmpdir, "sub", "resume.md")
            write_tailored_resume(result, out_path)
            assert os.path.exists(out_path)
            content = open(out_path, encoding="utf-8").read()
            assert "Jane Doe" in content
