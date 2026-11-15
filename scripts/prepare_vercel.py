"""Validate deployment inputs and place browser assets on Vercel's CDN.

Run from any directory: python scripts/prepare_vercel.py
Templates and compact telemetry remain private files inside the Python bundle.
"""
from pathlib import Path
import json
from shutil import copytree

ROOT = Path(__file__).resolve().parents[1]


def prepare(root: Path = ROOT) -> None:
    required = [root / "templates" / "index.html", root / "data" / "season_2024.json"]
    required += [root / "static" / name for name in ("app.js", "styles.css", "plotly.min.js")]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Incomplete upload. Add these project files before deploying: " + ", ".join(missing))
    manifest = json.loads((root / "data" / "season_2024.json").read_text(encoding="utf-8"))
    records = manifest.get("sessions", [])
    if not manifest.get("complete") or len(records) != 24:
        raise SystemExit("The complete 24-session dataset must be included in data/ before deployment.")
    for record in records:
        path = root / "data" / f"{record['id']}.json"
        if not path.is_file():
            raise SystemExit(f"Incomplete upload: add data/{path.name} before deploying.")
        session = json.loads(path.read_text(encoding="utf-8"))
        if session.get("id") != record["id"] or len(session.get("drivers", [])) < 2:
            raise SystemExit(f"Invalid session file: data/{path.name}")
    destination = root / "public" / "static"
    copytree(root / "static", destination, dirs_exist_ok=True)
    print(f"Verified {len(records)} qualifying sessions and templates/index.html.")
    print("Prepared public/static/ for CDN delivery; the Python bundle keeps templates/ and data/*.json.")


if __name__ == "__main__":
    prepare()
