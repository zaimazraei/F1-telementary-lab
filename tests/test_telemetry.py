"""Scientific invariants and source provenance, not chart implementation tests."""
import hashlib
import json

import numpy as np
import pytest

import telemetry


def test_bundled_data_matches_frozen_source_hashes():
    provenance = json.loads((telemetry.DATA_DIR / "provenance.json").read_text())
    assert len(provenance["commit"]) == 40
    for record in provenance["files"]:
        raw = (telemetry.ROOT / record["local_file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == record["sha256"]


def test_selected_laps_are_fastest_accurate_undeleted_flying_laps():
    session = telemetry._read_session("2024_bahrain_q")
    for driver in session["drivers"]:
        raw = json.loads((telemetry.DATA_DIR / "raw" / "2024_bahrain_q" / f"{driver['code']}_laptimes.json").read_text())
        valid = [i for i, t in enumerate(raw["time"]) if isinstance(t, (int, float))
                 and raw["iacc"][i] and not raw["del"][i]
                 and raw["pin"][i] == "None" and raw["pout"][i] == "None"]
        best = min(valid, key=lambda i: raw["time"][i])
        assert driver["lap_time"] == raw["time"][best]
        assert driver["lap_number"] == raw["lap"][best]
        assert sum(driver["sectors"]) == pytest.approx(driver["lap_time"])


def test_swap_reverses_delta_and_preserves_official_sector_gap():
    forward = telemetry.compare_laps("2024_bahrain_q", "VER", "LEC")
    reverse = telemetry.compare_laps("2024_bahrain_q", "LEC", "VER")
    assert forward["lap_delta"] == pytest.approx(-0.014)
    assert reverse["lap_delta"] == pytest.approx(0.014)
    assert forward["telemetry"]["distance"] == reverse["telemetry"]["distance"]
    assert np.asarray(forward["telemetry"]["delta"]) == pytest.approx(-np.asarray(reverse["telemetry"]["delta"]))
    assert sum(s["delta"] for s in forward["sectors"]) == pytest.approx(forward["lap_delta"])
    assert forward["drivers"]["a"]["qualifying_segment"] == "Q3"
    assert forward["drivers"]["b"]["qualifying_segment"] == "Q2"


def test_trace_is_monotonic_finite_binary_and_not_forced_to_official_gap():
    result = telemetry.compare_laps("2024_bahrain_q", "VER", "LEC")
    trace = result["telemetry"]
    length = len(trace["distance"])
    for values in trace.values():
        assert len(values) == length
        assert np.isfinite(values).all()
    assert (np.diff(trace["distance"]) > 0).all()
    assert (np.diff(trace["elapsed_a"]) > 0).all()
    assert (np.diff(trace["elapsed_b"]) > 0).all()
    assert set(trace["brake_a"]) == {0, 1}
    assert set(trace["brake_b"]) == {0, 1}
    assert trace["delta"][0] == 0
    assert abs(trace["delta"][-1] - result["lap_delta"]) > 0.1
    assert sum(section["gain"] for section in result["mini_sectors"]) == pytest.approx(trace["delta"][-1], abs=0.00002)


def test_binary_resampling_holds_previous_state():
    actual = telemetry._previous_sample(np.array([0, 4.9, 5, 9.9, 10]),
                                        np.array([0, 5, 10]), np.array([0, 1, 0]))
    np.testing.assert_array_equal(actual, [0, 0, 1, 1, 0])


@pytest.mark.parametrize("session,a,b", [("../outside", "VER", "LEC"),
                                        ("missing", "VER", "LEC"),
                                        ("2024_bahrain_q", "XXX", "LEC"),
                                        ("2024_bahrain_q", "VER", "VER")])
def test_invalid_selections_fail_clearly(session, a, b):
    with pytest.raises(ValueError):
        telemetry.compare_laps(session, a, b)


def test_import_without_auth_never_starts_network_or_prompts(monkeypatch):
    import fastf1
    from fastf1.internals.f1account import token_manager

    monkeypatch.setattr(token_manager, "get_stored", lambda: None)
    monkeypatch.setattr(fastf1, "get_session", lambda *args: pytest.fail("Network path entered without authentication"))
    with pytest.raises(RuntimeError, match="authenticate"):
        telemetry.import_fastf1(2024, "Bahrain")
