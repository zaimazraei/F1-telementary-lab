"""Actual local dates must survive postponements and UTC midnight crossings."""
import json

import pytest

from scripts.fetch_season import DATA, DataUnavailable, actual_session_date


@pytest.mark.parametrize("session_id,expected,scheduled", [
    ("2024_sao_paulo_q", "2024-11-03", "2024-11-02"),
    ("2024_las_vegas_q", "2024-11-22", "2024-11-22"),
    ("2024_bahrain_q", "2024-03-01", "2024-03-01"),
])
def test_actual_local_date_uses_raw_session_timing(session_id, expected, scheduled):
    info = json.loads((DATA / "raw" / session_id / "session_info.json").read_text())
    assert info["session_info"]["StartDate"][:10] == scheduled
    assert actual_session_date(info) == (expected, "actual_local_session_start")
    saved = json.loads((DATA / f"{session_id}.json").read_text(encoding="utf-8"))
    assert saved["date"] == expected
    assert saved["date_basis"] == "actual_local_session_start"


def test_missing_actual_timing_is_explicitly_scheduled_fallback():
    assert actual_session_date({"session_info": {"StartDate": "2024-11-02T15:00:00"}}) == (
        "2024-11-02", "scheduled_session_start_fallback")


def test_missing_both_dates_is_reported_instead_of_invented():
    with pytest.raises(DataUnavailable, match="date"):
        actual_session_date({})


def test_timezone_aware_utc_timestamp_converts_to_local_previous_day():
    info = {"t0_date": "2024-11-23T05:00:00+00:00", "session_start_time": 0,
            "session_info": {"GmtOffset": "-08:00:00", "StartDate": "2024-11-23T01:00:00"}}
    assert actual_session_date(info) == ("2024-11-22", "actual_local_session_start")
