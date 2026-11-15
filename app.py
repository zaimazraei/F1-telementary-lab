"""Local web server for the F1 Telemetry Lab. Run with: python app.py."""
from __future__ import annotations

import csv
import io
import logging
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request
from jinja2 import TemplateNotFound

from telemetry import compare_laps, get_catalog, import_fastf1

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, template_folder=str(ROOT / "templates"),
            static_folder=str(ROOT / "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
app.config["FASTF1_IMPORT_ENABLED"] = os.environ.get("VERCEL") != "1"
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
imports = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fastf1-import")


@app.get("/")
def index():
    return render_template("index.html", fastf1_import_enabled=app.config["FASTF1_IMPORT_ENABLED"])


@app.get("/api/health")
def health():
    return jsonify(status="ok")


@app.get("/api/catalog")
def catalog():
    data = get_catalog()
    if not data["sessions"]:
        return jsonify(error="The saved dataset is missing from this deployment. Include the data folder and redeploy."), 503
    return jsonify(data)


def selected_comparison():
    session = request.args.get("session", "").strip()
    driver_a = request.args.get("driver_a", "").strip().upper()
    driver_b = request.args.get("driver_b", "").strip().upper()
    if not session or not driver_a or not driver_b:
        raise ValueError("Choose a session and two drivers first.")
    if driver_a == driver_b:
        raise ValueError("Choose two different drivers to compare.")
    return compare_laps(session, driver_a, driver_b)


@app.get("/api/compare")
def compare():
    return jsonify(selected_comparison())


@app.get("/api/export")
def export():
    comparison = selected_comparison()
    data = comparison["telemetry"]
    columns = list(data)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    # Metadata columns make exported traces interpretable outside the dashboard.
    metadata = ["session", "driver_a", "driver_b", "delta_definition", "source"]
    writer.writerow(metadata + columns)
    session = comparison["session"]
    drivers = comparison["drivers"]
    for row in zip(*(data[column] for column in columns)):
        writer.writerow([
            session["title"], drivers["a"]["code"], drivers["b"]["code"],
            "elapsed_b_minus_elapsed_a_seconds", session.get("source_url", ""),
            *row,
        ])
    # Driver codes come from the validated catalog, never raw query strings.
    name = f"telemetry-{drivers['a']['code']}-{drivers['b']['code']}.csv"
    return Response(output.getvalue(), mimetype="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "Cache-Control": "no-store",
    })


def run_import(job_id: str, year: int, event: str):
    try:
        session_id = import_fastf1(year, event)
        result = {"status": "complete", "session_id": session_id}
    except Exception as exc:
        app.logger.exception("FastF1 session import failed")
        result = {"status": "error", "error": str(exc)}
    with jobs_lock:
        jobs[job_id] = result


@app.post("/api/import")
def import_session():
    if not app.config["FASTF1_IMPORT_ENABLED"]:
        return jsonify(error="Live FastF1 imports are available in the local app. This hosted dashboard uses the saved 2024 dataset."), 403
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("Send a year and an event name.")
    year = body.get("year")
    if isinstance(year, bool) or (isinstance(year, float) and not year.is_integer()):
        raise ValueError("Enter a valid season year.")
    try:
        year = int(year)
    except (TypeError, ValueError):
        raise ValueError("Enter a valid season year.") from None
    if not 2018 <= year <= datetime.now().year:
        raise ValueError(f"Choose a year from 2018 to {datetime.now().year}.")
    event = body.get("event")
    if not isinstance(event, str) or not 1 <= len(event.strip()) <= 100:
        raise ValueError("Enter an event name, for example Bahrain or Monza.")
    with jobs_lock:
        if any(job["status"] == "running" for job in jobs.values()):
            return jsonify(error="A session is already loading. Please wait for it to finish."), 409
        # Bound this small process-local status store.
        if len(jobs) >= 40:
            jobs.pop(next(iter(jobs)))
        job_id = uuid.uuid4().hex
        jobs[job_id] = {"status": "running"}
    imports.submit(run_import, job_id, year, event.strip())
    return jsonify(job_id=job_id), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if job is None:
        return jsonify(error="This loading task was not found. Try importing the session again."), 404
    return jsonify(job)


@app.errorhandler(ValueError)
def invalid_request(exc):
    return jsonify(error=str(exc)), 400


@app.errorhandler(KeyError)
@app.errorhandler(FileNotFoundError)
def missing_data(exc):
    return jsonify(error="That session or driver is unavailable. Refresh the session list and try again."), 404


@app.errorhandler(500)
def server_error(exc):
    return jsonify(error="The request could not be completed. Check the server or deployment logs for details."), 500


@app.errorhandler(TemplateNotFound)
def missing_template(exc):
    app.logger.error("Dashboard template missing: %s", exc)
    return jsonify(error="Dashboard template is missing from this deployment. Include templates/index.html and redeploy."), 500


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("PORT", "8050"))
    print(f"\nF1 Telemetry Lab: http://127.0.0.1:{port}\n", flush=True)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
