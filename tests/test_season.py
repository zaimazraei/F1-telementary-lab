"""Offline audit of the complete 2024 qualifying collection and chart coverage.

These tests compare saved outputs to the downloaded upstream evidence. They do
not refresh a source, call an API, or substitute generated data for missing laps.
"""
import hashlib
import json
import math

import numpy as np
import pytest

import telemetry


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest():
    path = telemetry.DATA_DIR / "season_2024.json"
    assert path.is_file(), "Build the full 2024 collection before running its audit."
    return read_json(path)


@pytest.fixture(scope="module")
def sessions(manifest):
    return [read_json(telemetry.DATA_DIR / f"{row['id']}.json") for row in manifest["sessions"]]


def valid_lap_indices(laps):
    """Independent interpretation of the published source's validity columns."""
    return [
        index for index, lap_time in enumerate(laps["time"])
        if isinstance(lap_time, (int, float))
        and not isinstance(lap_time, bool)
        and math.isfinite(lap_time)
        and lap_time > 0
        and laps["iacc"][index] is True
        and laps["del"][index] is False
        and laps["pin"][index] in (None, "None")
        and laps["pout"][index] in (None, "None")
    ]


def test_manifest_covers_all_24_qualifying_sessions(manifest, sessions):
    assert manifest["year"] == 2024
    assert manifest["complete"] is True
    assert manifest["session_count"] == len(sessions) == 24
    assert not manifest["download_errors"]
    assert len({s["id"] for s in sessions}) == 24
    assert len({s["event"] for s in sessions}) == 24
    assert len({s["date"] for s in sessions}) == 24
    source_index = read_json(telemetry.DATA_DIR / "source_index_2024.json")
    assert source_index["sha"] == manifest["commit"]
    expected_events = {entry["path"] for entry in source_index["tree"]
                       if entry["type"] == "tree" and entry["path"].endswith(" Grand Prix")}
    assert {s["event"] for s in sessions} == expected_events
    assert all(s["year"] == 2024 and s["session"] == "Qualifying" for s in sessions)
    assert manifest["expected_driver_appearances"] == sum(s["expected_driver_count"] for s in sessions)
    assert manifest["usable_driver_appearances"] == sum(len(s["drivers"]) for s in sessions)
    codes = {d["code"] for s in sessions for d in s["drivers"]}
    assert set(manifest["unique_driver_codes"]) == codes


def test_every_entered_driver_is_included_or_explained(sessions):
    for session in sessions:
        raw = telemetry.DATA_DIR / "raw" / session["id"]
        entrants = read_json(raw / "drivers.json")["drivers"]
        expected = {d["driver"] for d in entrants}
        included = [d["code"] for d in session["drivers"]]
        unavailable = session["unavailable_drivers"]
        missing = [d["code"] for d in unavailable]
        assert len(included) == len(set(included)), session["id"]
        assert len(missing) == len(set(missing)), session["id"]
        assert not set(included) & set(missing), session["id"]
        assert set(included) | set(missing) == expected, session["id"]
        assert session["expected_driver_count"] == len(expected), session["id"]
        assert session["usable_driver_count"] == len(included), session["id"]
        assert len(included) >= 2, session["id"]
        for item in unavailable:
            assert item["name"] and item["reason"], (session["id"], item)
            assert item["kind"] == "data_unavailable", (session["id"], item)


def test_raw_evidence_has_matching_hashes_and_pinned_commit(manifest, sessions):
    commit = manifest["commit"]
    assert len(commit) == 40
    for session in sessions:
        provenance = read_json(telemetry.DATA_DIR / "provenance" / f"{session['id']}.json")
        assert provenance["commit"] == commit, session["id"]
        paths = [record["local_file"] for record in provenance["files"]]
        assert len(paths) == len(set(paths)), session["id"]
        for record in provenance["files"]:
            assert f"/{commit}/" in record["url"], record["url"]
            payload = (telemetry.ROOT / record["local_file"]).read_bytes()
            assert len(payload) == record["bytes"], record["local_file"]
            assert hashlib.sha256(payload).hexdigest() == record["sha256"], record["local_file"]
        for driver in session["drivers"]:
            for name in (f"{driver['code']}_laptimes.json", f"{driver['code']}_{driver['lap_number']}_tel.json"):
                assert any(path.endswith(f"/{session['id']}/{name}") for path in paths), (session["id"], name)


def test_selected_laps_and_channels_match_upstream_without_invented_fill(sessions):
    for session in sessions:
        raw_dir = telemetry.DATA_DIR / "raw" / session["id"]
        for driver in session["drivers"]:
            label = (session["id"], driver["code"])
            laps = read_json(raw_dir / f"{driver['code']}_laptimes.json")
            valid = valid_lap_indices(laps)
            assert valid, label
            best = min(valid, key=lambda index: laps["time"][index])
            assert driver["lap_time"] == laps["time"][best], label
            assert driver["lap_number"] == laps["lap"][best], label
            assert driver["qualifying_segment"] == laps.get("qs", [None] * len(laps["time"]))[best], label
            assert driver["compound"] == laps["compound"][best], label
            for number, sector in enumerate(driver["sectors"], 1):
                original = laps[f"s{number}"][best]
                assert sector == (None if original == "None" else original), label
            if all(isinstance(value, (int, float)) and math.isfinite(value) for value in driver["sectors"]):
                assert sum(driver["sectors"]) == pytest.approx(driver["lap_time"], abs=0.003), label
            source = read_json(raw_dir / f"{driver['code']}_{driver['lap_number']}_tel.json")["tel"]
            for channel in ("time", "distance", "speed", "throttle", "brake"):
                assert driver["telemetry"][channel] == source[channel], (label, channel)
            for channel in ("x", "y"):
                assert (channel in driver["telemetry"]) == (channel in source), (label, channel)
                if channel in source:
                    assert driver["telemetry"][channel] == source[channel], (label, channel)


def test_reported_exclusions_agree_with_saved_lap_evidence(sessions):
    for session in sessions:
        raw_dir = telemetry.DATA_DIR / "raw" / session["id"]
        for missing in session["unavailable_drivers"]:
            label = (session["id"], missing["code"])
            laps = read_json(raw_dir / f"{missing['code']}_laptimes.json")
            valid = valid_lap_indices(laps)
            if not valid:
                assert "No accurate" in missing["reason"], label
            else:
                best = min(valid, key=lambda index: laps["time"][index])
                filename = f"{missing['code']}_{int(laps['lap'][best])}_tel.json"
                assert not (raw_dir / filename).exists(), label
                assert "absent" in missing["reason"].lower() or "missing" in missing["reason"].lower(), label


def test_every_included_driver_can_render_finite_aligned_charts(sessions):
    for session in sessions:
        drivers = session["drivers"]
        for index, driver in enumerate(drivers):
            opponent = drivers[(index + 1) % len(drivers)]
            result = telemetry.compare_laps(session["id"], driver["code"], opponent["code"])
            label = (session["id"], driver["code"], opponent["code"])
            trace = result["telemetry"]
            size = len(trace["distance"])
            assert size > 100, label
            assert all(len(values) == size and np.isfinite(values).all() for values in trace.values()), label
            assert (np.diff(trace["distance"]) > 0).all(), label
            assert (np.diff(trace["elapsed_a"]) >= 0).all(), label
            assert (np.diff(trace["elapsed_b"]) >= 0).all(), label
            assert set(trace["brake_a"]).issubset({0, 1}), label
            assert set(trace["brake_b"]).issubset({0, 1}), label
            np.testing.assert_allclose(trace["delta"], np.asarray(trace["elapsed_b"]) - trace["elapsed_a"], atol=1.1e-6, err_msg=str(label))
            assert result["lap_delta"] == pytest.approx(opponent["lap_time"] - driver["lap_time"]), label
            json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("session_id", ["2024_bahrain_q", "2024_monaco_q", "2024_belgian_q", "2024_sao_paulo_q"])
def test_swapping_drivers_preserves_comparison_conventions(sessions, session_id):
    session = next(s for s in sessions if s["id"] == session_id)
    first, second = session["drivers"][:2]
    a = telemetry.compare_laps(session_id, first["code"], second["code"])
    b = telemetry.compare_laps(session_id, second["code"], first["code"])
    assert a["telemetry"]["distance"] == b["telemetry"]["distance"]
    np.testing.assert_allclose(a["telemetry"]["delta"], -np.asarray(b["telemetry"]["delta"]), atol=1e-6)
    assert a["lap_delta"] == pytest.approx(-b["lap_delta"])
    assert [s["delta"] for s in a["sectors"]] == pytest.approx([-s["delta"] for s in b["sectors"]])


def test_catalog_covers_bundled_sessions_without_large_telemetry_payloads(sessions):
    catalog = telemetry.get_catalog()["sessions"]
    by_id = {s["id"]: s for s in catalog}
    assert len(by_id) == len(catalog)
    for session in sessions:
        row = by_id[session["id"]]
        assert {d["code"] for d in row["drivers"]} == {d["code"] for d in session["drivers"]}
        assert all("telemetry" not in d for d in row["drivers"])
