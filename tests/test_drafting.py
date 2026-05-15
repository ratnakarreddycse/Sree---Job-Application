from datetime import date

from job_applications.drafting import build_application_draft, write_application_drafts


def test_build_application_draft_contains_role_and_company() -> None:
    record = {
        "company": "Contoso",
        "role": "Data Engineer",
        "action": "apply_now",
        "score": 90,
        "reasons": ["Strong role-title match"],
        "notes": "Remote USA. H1B supported",
    }

    draft = build_application_draft(record, generated_on=date(2026, 4, 25))

    assert "Data Engineer at Contoso" in draft
    assert "Pipeline action: apply_now" in draft
    assert "Generated on: 2026-04-25" in draft


def test_write_application_drafts_creates_ordered_markdown_files(tmp_path) -> None:
    records = [
        {"company": "A", "role": "Data Engineer", "action": "apply_now", "score": 80, "reasons": [], "notes": ""},
        {"company": "B", "role": "Analytics Engineer", "action": "review_fast", "score": 70, "reasons": [], "notes": ""},
    ]

    created = write_application_drafts(records, tmp_path, generated_on=date(2026, 4, 25))

    assert len(created) == 2
    assert created[0].name.startswith("01_")
    assert created[1].name.startswith("02_")
    assert created[0].suffix == ".md"
