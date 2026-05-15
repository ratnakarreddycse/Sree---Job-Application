from job_applications.cli import _build_best_apply_url_map, _score_apply_url_specificity


def test_score_apply_url_specificity_prefers_direct_posting_over_listing() -> None:
    listing = "https://www.databricks.com/company/careers/open-positions"
    direct = "https://boards.greenhouse.io/example/jobs/1234567"

    assert _score_apply_url_specificity(direct) > _score_apply_url_specificity(listing)


def test_build_best_apply_url_map_uses_most_specific_url_for_same_role() -> None:
    records = [
        {
            "company": "Databricks",
            "role": "Senior Data Engineer",
            "status": "new",
            "notes": "Link: https://www.databricks.com/company/careers/open-positions",
        },
        {
            "company": "Databricks",
            "role": "Senior Data Engineer",
            "status": "new",
            "notes": "Link: https://boards.greenhouse.io/databricks/jobs/9876543",
        },
    ]

    best = _build_best_apply_url_map(records)

    assert best[("databricks", "senior data engineer")] == "https://boards.greenhouse.io/databricks/jobs/9876543"
