"""A growing offline dataset must not leave the session selector stale."""
import json

import telemetry


def test_catalog_detects_new_and_replaced_session_files(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "DATA_DIR", tmp_path)
    monkeypatch.setattr(telemetry, "IMPORTED_DIR", tmp_path / "imports")
    first = {"id": "2024_test_q", "year": 2024, "event": "Test", "date": "2024-03-01",
             "drivers": [{"code": "AAA", "name": "Driver A", "lap_time": 90,
                          "telemetry": {"distance": [0, 1]}}]}
    path = tmp_path / "2024_test_q.json"
    path.write_text(json.dumps(first))
    catalog = telemetry.get_catalog()
    assert catalog["season_summary"]["driver_lap_count"] == 1
    assert "telemetry" not in catalog["sessions"][0]["drivers"][0]

    first["drivers"].append({"code": "BBB", "name": "Driver B", "lap_time": 91})
    first["unavailable_drivers"] = [{"code": "CCC", "name": "Driver C", "reason": "No timed lap"}]
    path.write_text(json.dumps(first))
    updated = telemetry.get_catalog()
    assert updated["season_summary"]["driver_lap_count"] == 2
    assert updated["season_summary"]["unique_driver_count"] == 3
    assert updated["season_summary"]["unavailable_driver_count"] == 1

    second = {**first, "id": "2024_later_q", "date": "2024-12-01"}
    (tmp_path / "2024_later_q.json").write_text(json.dumps(second))
    # A manifest is metadata, not a selectable session.
    (tmp_path / "season_2024.json").write_text(json.dumps({"year": 2024, "sessions": []}))
    final = telemetry.get_catalog()
    assert [s["id"] for s in final["sessions"]] == ["2024_test_q", "2024_later_q"]
    assert final["season_summary"]["session_count"] == 2


def test_recent_session_cache_detects_updated_lap(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "DATA_DIR", tmp_path)
    monkeypatch.setattr(telemetry, "IMPORTED_DIR", tmp_path / "imports")
    path = tmp_path / "2024_test_q.json"
    path.write_text(json.dumps({"id": "2024_test_q", "drivers": [], "title": "First"}))
    assert telemetry._read_session("2024_test_q")["title"] == "First"
    path.write_text(json.dumps({"id": "2024_test_q", "drivers": [], "title": "Updated on disk"}))
    assert telemetry._read_session("2024_test_q")["title"] == "Updated on disk"
