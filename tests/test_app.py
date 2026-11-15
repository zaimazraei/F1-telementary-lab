"""HTTP-level checks of the local dashboard; these never download F1 data."""
import csv
import io

import pytest

import app as server


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(server.app.config, "TESTING", True)
    with server.jobs_lock:
        server.jobs.clear()
    with server.app.test_client() as client:
        yield client
    with server.jobs_lock:
        server.jobs.clear()


@pytest.fixture
def selection(client):
    response = client.get("/api/catalog")
    assert response.status_code == 200
    sessions = response.get_json()["sessions"]
    assert sessions, "The app must include a real session for offline first use."
    session = sessions[0]
    assert len(session["drivers"]) >= 2
    return {
        "session": session["id"],
        "driver_a": session["drivers"][0]["code"],
        "driver_b": session["drivers"][1]["code"],
    }


def test_health(client):
    assert client.get("/api/health").get_json() == {"status": "ok"}


def test_comparison_is_json_with_consistent_arrays(client, selection):
    response = client.get("/api/compare", query_string=selection)
    assert response.status_code == 200
    data = response.get_json()
    assert data["drivers"]["a"]["code"] == selection["driver_a"]
    assert data["drivers"]["b"]["code"] == selection["driver_b"]
    assert data["session"]["source_url"].startswith("https://")
    arrays = data["telemetry"]
    assert len(arrays["distance"]) > 100
    assert {len(value) for value in arrays.values()} == {len(arrays["distance"])}
    assert b"NaN" not in response.data
    assert b"Infinity" not in response.data


def test_driver_swap_reverses_gap(client, selection):
    forward = client.get("/api/compare", query_string=selection).get_json()
    reverse_selection = {**selection, "driver_a": selection["driver_b"], "driver_b": selection["driver_a"]}
    reverse = client.get("/api/compare", query_string=reverse_selection).get_json()
    assert reverse["lap_delta"] == pytest.approx(-forward["lap_delta"])
    assert reverse["telemetry"]["delta"] == pytest.approx([-x for x in forward["telemetry"]["delta"]])


def test_export_has_same_values_and_provenance_as_chart(client, selection):
    comparison = client.get("/api/compare", query_string=selection).get_json()
    response = client.get("/api/export", query_string=selection)
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment;" in response.headers["Content-Disposition"]
    rows = list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))
    assert len(rows) == len(comparison["telemetry"]["distance"])
    assert rows[0]["driver_a"] == selection["driver_a"]
    assert rows[0]["driver_b"] == selection["driver_b"]
    assert rows[0]["source"] == comparison["session"]["source_url"]
    assert rows[0]["delta_definition"] == "elapsed_b_minus_elapsed_a_seconds"
    for index in (0, len(rows) // 2, len(rows) - 1):
        assert float(rows[index]["delta"]) == pytest.approx(comparison["telemetry"]["delta"][index])


@pytest.mark.parametrize("route", ["/api/compare", "/api/export"])
def test_missing_selection_has_readable_error(client, route):
    response = client.get(route)
    assert response.status_code == 400
    assert "Choose" in response.get_json()["error"]


def test_identical_driver_is_rejected(client, selection):
    response = client.get("/api/compare", query_string={**selection, "driver_b": selection["driver_a"]})
    assert response.status_code == 400
    assert "different" in response.get_json()["error"]


@pytest.mark.parametrize("field,value", [("session", "does-not-exist"), ("driver_a", "ZZZ")])
def test_unknown_selection_is_rejected(client, selection, field, value):
    response = client.get("/api/compare", query_string={**selection, field: value})
    assert response.status_code in (400, 404)
    assert response.get_json()["error"]


@pytest.mark.parametrize("payload", [None, [], {}, {"year": True, "event": "Bahrain"}, {"year": 2024.9, "event": "Bahrain"}, {"year": 2010, "event": "Bahrain"}, {"year": "no", "event": "Bahrain"}, {"year": 2024, "event": "  "}, {"year": 2024, "event": []}])
def test_bad_import_parameters_never_start_work(client, monkeypatch, payload):
    def forbidden(*args, **kwargs):
        raise AssertionError("Invalid inputs must not start a data download.")
    monkeypatch.setattr(server.imports, "submit", forbidden)
    response = client.post("/api/import", json=payload)
    assert response.status_code == 400
    assert response.get_json()["error"]


def test_import_job_success_and_polling(client, monkeypatch):
    def fake_import(year, event):
        assert (year, event) == (2024, "Bahrain")
        return "imported-test-session"
    monkeypatch.setattr(server, "import_fastf1", fake_import)
    monkeypatch.setattr(server.imports, "submit", lambda fn, *args: fn(*args))
    response = client.post("/api/import", json={"year": 2024, "event": " Bahrain "})
    assert response.status_code == 202
    job = client.get(f"/api/jobs/{response.get_json()['job_id']}")
    assert job.get_json() == {"status": "complete", "session_id": "imported-test-session"}


def test_import_failure_is_reported_to_ui(client, monkeypatch):
    def fail_import(*args):
        raise RuntimeError("Please sign in locally before importing this session.")
    monkeypatch.setattr(server, "import_fastf1", fail_import)
    monkeypatch.setattr(server.imports, "submit", lambda fn, *args: fn(*args))
    response = client.post("/api/import", json={"year": 2024, "event": "Bahrain"})
    assert response.status_code == 202
    job = client.get(f"/api/jobs/{response.get_json()['job_id']}").get_json()
    assert job["status"] == "error"
    assert "sign in" in job["error"]


def test_only_one_download_runs_at_a_time(client, monkeypatch):
    monkeypatch.setattr(server.imports, "submit", lambda *args: None)
    first = client.post("/api/import", json={"year": 2024, "event": "Bahrain"})
    second = client.post("/api/import", json={"year": 2024, "event": "Monza"})
    assert first.status_code == 202
    assert second.status_code == 409
    assert client.get(f"/api/jobs/{first.get_json()['job_id']}").get_json()["status"] == "running"


def test_unknown_job_is_readable(client):
    response = client.get("/api/jobs/not-a-job")
    assert response.status_code == 404
    assert response.get_json()["error"]
