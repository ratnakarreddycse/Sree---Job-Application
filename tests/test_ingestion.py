from pathlib import Path
from unittest.mock import MagicMock, patch

from job_applications.ingestion import dedupe_records, fetch_ats_records, load_records_from_file


def test_load_records_from_csv_maps_title_to_role(tmp_path: Path) -> None:
    csv_path = tmp_path / "jobs.csv"
    csv_path.write_text(
        "company,title,status,description\nContoso,Data Engineer,new,Python SQL ETL\n",
        encoding="utf-8",
    )

    records = load_records_from_file(csv_path)

    assert records == [
        {
            "company": "Contoso",
            "role": "Data Engineer",
            "status": "new",
            "notes": "Python SQL ETL",
            "apply_url": "",
        }
    ]


def test_dedupe_records_removes_duplicates() -> None:
    deduped = dedupe_records(
        [
            {"company": "Contoso", "role": "Data Engineer", "status": "new", "notes": "A"},
            {"company": "Contoso", "role": "Data Engineer", "status": "new", "notes": "A"},
            {"company": "Contoso", "role": "Data Engineer", "status": "new", "notes": "B"},
        ]
    )

    assert len(deduped) == 2


# ---------------------------------------------------------------------------
# fetch_ats_records tests
# ---------------------------------------------------------------------------

_GREENHOUSE_RESPONSE = {
    "jobs": [
        {
            "id": 123,
            "title": "Senior Data Engineer",
            "absolute_url": "https://example.com/company/careers/jobs?gh_jid=123",
            "location": {"name": "Remote - US"},
        },
        {
            "id": 456,
            "title": "Android Engineer",
            "absolute_url": "https://example.com/company/careers/jobs?gh_jid=456",
            "location": {"name": "San Francisco, CA"},
        },
    ]
}

_LEVER_RESPONSE = [
    {
        "id": "abc-123",
        "text": "Data Platform Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/abc-123",
        "categories": {"location": "Remote"},
        "descriptionPlain": "Build data pipelines and ETL systems.",
    },
    {
        "id": "def-456",
        "text": "Marketing Manager",
        "hostedUrl": "https://jobs.lever.co/acme/def-456",
        "categories": {"location": "New York"},
        "descriptionPlain": "Lead marketing campaigns.",
    },
]

_ASHBY_RESPONSE = {
    "jobs": [
        {
            "id": "uuid-1",
            "title": "Analytics Engineer",
            "jobUrl": "https://jobs.ashbyhq.com/acme/uuid-1",
            "location": "Remote, United States",
            "descriptionPlain": "Build dbt models and data pipelines.",
        },
        {
            "id": "uuid-2",
            "title": "Sales Manager",
            "jobUrl": "https://jobs.ashbyhq.com/acme/uuid-2",
            "location": "Austin, TX",
            "descriptionPlain": "Lead sales team.",
        },
    ]
}


def _mock_ats_request(url: str) -> object:
    if "greenhouse" in url:
        return _GREENHOUSE_RESPONSE
    if "lever" in url:
        return _LEVER_RESPONSE
    if "ashby" in url:
        return _ASHBY_RESPONSE
    return {}


@patch("job_applications.ingestion._ats_request", side_effect=_mock_ats_request)
def test_fetch_ats_records_greenhouse_keyword_filter(mock_req: MagicMock) -> None:
    boards = [{"type": "greenhouse", "slug": "acme", "company": "Acme", "keywords": ["data engineer"]}]
    records = fetch_ats_records(boards)

    assert len(records) == 1
    assert records[0]["role"] == "Senior Data Engineer"
    assert records[0]["apply_url"] == "https://example.com/company/careers/jobs?gh_jid=123"
    assert records[0]["company"] == "Acme"


@patch("job_applications.ingestion._ats_request", side_effect=_mock_ats_request)
def test_fetch_ats_records_lever_keyword_filter(mock_req: MagicMock) -> None:
    boards = [{"type": "lever", "slug": "acme", "company": "Acme", "keywords": ["data platform"]}]
    records = fetch_ats_records(boards)

    assert len(records) == 1
    assert records[0]["role"] == "Data Platform Engineer"
    assert records[0]["apply_url"] == "https://jobs.lever.co/acme/abc-123"


@patch("job_applications.ingestion._ats_request", side_effect=_mock_ats_request)
def test_fetch_ats_records_ashby_keyword_filter(mock_req: MagicMock) -> None:
    boards = [{"type": "ashby", "slug": "acme", "company": "Acme", "keywords": ["analytics engineer"]}]
    records = fetch_ats_records(boards)

    assert len(records) == 1
    assert records[0]["role"] == "Analytics Engineer"
    assert records[0]["apply_url"] == "https://jobs.ashbyhq.com/acme/uuid-1"


@patch("job_applications.ingestion._ats_request", side_effect=_mock_ats_request)
def test_fetch_ats_records_no_keywords_returns_all(mock_req: MagicMock) -> None:
    boards = [{"type": "greenhouse", "slug": "acme", "company": "Acme", "keywords": []}]
    records = fetch_ats_records(boards)

    assert len(records) == 2


@patch("job_applications.ingestion._ats_request", side_effect=_mock_ats_request)
def test_fetch_ats_records_respects_limit(mock_req: MagicMock) -> None:
    boards = [{"type": "greenhouse", "slug": "acme", "company": "Acme", "keywords": [], "limit": 1}]
    records = fetch_ats_records(boards)

    assert len(records) == 1


@patch("job_applications.ingestion._ats_request", side_effect=_mock_ats_request)
def test_fetch_ats_records_unknown_type_skipped(mock_req: MagicMock) -> None:
    boards = [{"type": "unknown_ats", "slug": "acme", "company": "Acme"}]
    records = fetch_ats_records(boards)

    assert records == []


@patch("job_applications.ingestion._ats_request", side_effect=Exception("network error"))
def test_fetch_ats_records_error_is_skipped(mock_req: MagicMock) -> None:
    boards = [{"type": "greenhouse", "slug": "acme", "company": "Acme"}]
    records = fetch_ats_records(boards)

    assert records == []
