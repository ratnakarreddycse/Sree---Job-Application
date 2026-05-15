from job_applications.pipeline import run_pipeline


def test_run_pipeline_counts_valid_and_invalid_records() -> None:
    summary = run_pipeline(
        [
            {"company": "Contoso", "role": "Engineer", "status": "Applied"},
            {"company": "Fabrikam", "role": "Analyst", "status": "Interview"},
            {"company": "", "role": "Designer", "status": "Draft"},
        ]
    )

    assert summary.total_records == 3
    assert summary.accepted_records == 2
    assert summary.rejected_records == 1
    assert summary.status_breakdown == {"applied": 1, "interview": 1}
    assert summary.action_breakdown == {"backlog": 2}


def test_run_pipeline_skips_roles_with_negative_visa_signal() -> None:
    summary = run_pipeline(
        [
            {
                "company": "Example Corp",
                "role": "Data Engineer",
                "status": "new",
                "notes": "No sponsorship available. US citizen only.",
            },
            {
                "company": "Open Data",
                "role": "Data Engineer",
                "status": "new",
                "notes": "H1B visa transfer supported. Python SQL ETL Airflow",
            },
        ]
    )

    assert summary.total_records == 2
    assert summary.accepted_records == 2
    assert summary.rejected_records == 0
    assert summary.top_recommendations[0]["company"] == "Open Data"
    assert summary.top_recommendations[0]["action"] in {"apply_now", "review_fast"}
    assert summary.top_recommendations[1]["action"] == "skip"
