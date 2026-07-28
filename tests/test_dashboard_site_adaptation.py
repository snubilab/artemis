import json
from pathlib import Path

from scripts.build_diagnosis_dashboard import build_adaptation_data

ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_adaptation_data_matches_fixture_compiler_results():
    data = build_adaptation_data()

    assert [
        (row["site"], row["changes"], row["granularityChanges"])
        for row in data["sites"]
    ] == [
        ("hospital_a", 1, 0),
        ("hospital_b", 4, 1),
        ("hospital_c", 1, 0),
    ]
    assert [
        (row["dpp4"], row["sulfonylurea"]) for row in data["sites"]
    ] == [
        ("populated", "absent"),
        ("absent", "absent"),
        ("absent", "populated"),
    ]
    assert len(data["items"]) == 21


def test_dashboard_narrative_entries_have_conclusions():
    for name in (
        "tte_dashboard_notes.json",
        "tte_issue_log.json",
        "tte_lab_notes.json",
    ):
        entries = json.loads((ROOT / "docs" / "daily_notes" / name).read_text())
        assert all(entry.get("key") for entry in entries)
