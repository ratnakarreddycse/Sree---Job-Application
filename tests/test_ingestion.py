from pathlib import Path

from job_applications.ingestion import dedupe_records, load_records_from_file


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
