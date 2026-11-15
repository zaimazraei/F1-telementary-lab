"""Deployment regressions: packaged assets, read-only requests and hosted mode."""
import builtins
import io
from pathlib import Path

from jinja2 import DictLoader
import pytest

import app as server
import telemetry


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(server.app.config, "TESTING", True)
    monkeypatch.setitem(server.app.config, "FASTF1_IMPORT_ENABLED", True)
    monkeypatch.setattr(server, "jobs", {})
    with server.app.test_client() as client:
        yield client


def test_dashboard_assets_and_data_do_not_depend_on_working_directory(client, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert "F1 Telemetry Lab" in response.get_data(as_text=True)
    assert client.get("/static/styles.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200
    catalog = client.get("/api/catalog")
    assert catalog.status_code == 200
    assert catalog.get_json()["sessions"]
    comparison = client.get("/api/compare", query_string={
        "session": "2024_bahrain_q", "driver_a": "VER", "driver_b": "LEC",
    })
    assert comparison.status_code == 200
    assert comparison.get_json()["lap_delta"] == pytest.approx(-0.014)


def test_missing_template_reports_a_deployment_problem(client, monkeypatch):
    environment = server.app.jinja_env
    monkeypatch.setattr(environment, "loader", DictLoader({}))
    environment.cache.clear()
    try:
        response = client.get("/")
    finally:
        environment.cache.clear()
    assert response.status_code == 500
    message = response.get_json()["error"]
    assert "template" in message.lower()
    assert "templates/index.html" in message
    assert "redeploy" in message.lower()
    assert "comparison" not in message.lower()
    assert "VS Code" not in message


def test_missing_dataset_is_not_reported_as_a_successful_empty_catalog(client, monkeypatch, tmp_path):
    monkeypatch.setattr(telemetry, "DATA_DIR", tmp_path)
    monkeypatch.setattr(telemetry, "IMPORTED_DIR", tmp_path / "imports")
    response = client.get("/api/catalog")
    assert response.status_code == 503
    assert "data" in response.get_json()["error"].lower()


def test_hosted_mode_rejects_import_before_validation_or_job_submission(client, monkeypatch):
    monkeypatch.setitem(server.app.config, "FASTF1_IMPORT_ENABLED", False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Hosted requests must not start a background download.")

    monkeypatch.setattr(server.imports, "submit", forbidden)
    monkeypatch.setattr(server, "import_fastf1", forbidden)
    for payload in ({"year": 2024, "event": "Bahrain"}, {}):
        response = client.post("/api/import", json=payload)
        assert response.status_code == 403
        assert response.get_json()["error"]
    assert server.jobs == {}


def test_hosted_dashboard_has_no_import_form_but_local_dashboard_does(client, monkeypatch):
    monkeypatch.setitem(server.app.config, "FASTF1_IMPORT_ENABLED", False)
    hosted = client.get("/")
    assert hosted.status_code == 200
    assert 'id="import-form"' not in hosted.get_data(as_text=True)
    assert 'id="session-select"' in hosted.get_data(as_text=True)
    monkeypatch.setitem(server.app.config, "FASTF1_IMPORT_ENABLED", True)
    local = client.get("/")
    assert local.status_code == 200
    assert 'id="import-form"' in local.get_data(as_text=True)


def test_bundled_requests_need_no_fastf1_import_or_writable_filesystem(client, monkeypatch):
    original_builtin_open = builtins.open
    original_io_open = io.open
    original_import = builtins.__import__

    def guard_open(original):
        def read_only(file, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise AssertionError(f"Bundled requests attempted a write: {file}")
            return original(file, mode, *args, **kwargs)
        return read_only

    def no_fastf1(name, *args, **kwargs):
        if name == "fastf1" or name.startswith("fastf1."):
            raise AssertionError("Viewing saved data must not import FastF1.")
        return original_import(name, *args, **kwargs)

    def no_directory_creation(*args, **kwargs):
        raise AssertionError("Viewing saved data must not create a runtime directory.")

    telemetry._cached_session.cache_clear()
    telemetry._catalog_entry.cache_clear()
    monkeypatch.setitem(server.app.config, "FASTF1_IMPORT_ENABLED", False)
    monkeypatch.setattr(builtins, "open", guard_open(original_builtin_open))
    monkeypatch.setattr(io, "open", guard_open(original_io_open))
    monkeypatch.setattr(builtins, "__import__", no_fastf1)
    monkeypatch.setattr(Path, "mkdir", no_directory_creation)
    assert client.get("/").status_code == 200
    assert client.get("/api/catalog").status_code == 200
    selection = {"session": "2024_bahrain_q", "driver_a": "VER", "driver_b": "LEC"}
    assert client.get("/api/compare", query_string=selection).status_code == 200
    assert client.get("/api/export", query_string=selection).status_code == 200
