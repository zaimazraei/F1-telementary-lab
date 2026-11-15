"""Fetch every 2024 qualifying driver's fastest valid lap, with resumable caching.

    python scripts/fetch_season.py
    python scripts/fetch_season.py --event Bahrain

Only exact Qualifying folders are used; practices, races, sprints and sprint
qualifying are excluded. Eight requests at most are active at once. Raw files
are pinned to one public Git commit and cached alongside their SHA-256 records.
Network errors are reported separately from missing or unusable source data.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import threading
import time
import unicodedata
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from telemetry import _clean_telemetry  # noqa: E402

DATA = ROOT / "data"
COMMIT = "d1543a71370d9b617b627319f8ad80b2f85dfd5e"
REPOSITORY = "TracingInsights/2024"
RAW_BASE = f"https://raw.githubusercontent.com/{REPOSITORY}/{COMMIT}"
SELECTION = "Fastest accurate, non-deleted flying lap across Q1/Q2/Q3 for each driver."
NETWORK_SLOTS = threading.Semaphore(8)
_THREAD_LOCAL = threading.local()


class DataUnavailable(Exception):
    """The pinned source does not contain sufficient valid data."""


class DownloadError(Exception):
    """The source could not be reached; not evidence that data is absent."""


def write_json(path: Path, value, pretty=False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False,
                                    indent=2 if pretty else None,
                                    separators=None if pretty else (",", ":")), encoding="utf-8")
    temporary.replace(path)


def request_bytes(url: str) -> bytes:
    if not hasattr(_THREAD_LOCAL, "http"):
        _THREAD_LOCAL.http = requests.Session()
        _THREAD_LOCAL.http.headers["User-Agent"] = "F1-Telemetry-Lab/1.0 (public data education)"
    for attempt in range(4):
        try:
            with NETWORK_SLOTS:
                response = _THREAD_LOCAL.http.get(url, timeout=(15, 60))
            if response.status_code == 404:
                raise DataUnavailable("Source file is absent at the pinned repository commit.")
            response.raise_for_status()
            return response.content
        except DataUnavailable:
            raise
        except requests.RequestException as exc:
            if attempt == 3:
                raise DownloadError(f"Download failed after four attempts ({type(exc).__name__}).") from exc
            time.sleep(0.6 * (2 ** attempt))
    raise DownloadError("Download did not finish.")


def session_id(event: str) -> str:
    text = event.removesuffix(" Grand Prix")
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "2024_" + re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_") + "_q"


def actual_session_date(info: dict) -> tuple[str, str]:
    """Use the actual start in circuit-local time, including postponed sessions.

    FastF1's t0_date is UTC even when serialized without a timezone suffix.
    The scheduled StartDate can be stale after a postponement, while the UTC
    calendar day can differ from the local day at night sessions such as Vegas.
    """
    session_info = info.get("session_info", {})
    try:
        seconds = info["session_start_time"]
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("No valid actual start offset")
        zero = datetime.fromisoformat(info["t0_date"].replace("Z", "+00:00"))
        if zero.tzinfo is None:
            zero = zero.replace(tzinfo=timezone.utc)
        offset = re.fullmatch(r"([+-]?)(\d{1,2}):(\d{2}):(\d{2})", session_info["GmtOffset"])
        if offset is None:
            raise ValueError("Missing circuit-local UTC offset")
        sign, hours, minutes, offset_seconds = offset.groups()
        hours, minutes, offset_seconds = int(hours), int(minutes), int(offset_seconds)
        if hours > 23 or minutes > 59 or offset_seconds > 59:
            raise ValueError("Invalid circuit-local UTC offset")
        zone = timezone(timedelta(hours=hours, minutes=minutes, seconds=offset_seconds)
                        * (-1 if sign == "-" else 1))
        local_start = (zero + timedelta(seconds=seconds)).astimezone(zone)
        return local_start.date().isoformat(), "actual_local_session_start"
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError):
        scheduled = session_info.get("StartDate")
        if isinstance(scheduled, str):
            try:
                return datetime.fromisoformat(scheduled.replace("Z", "+00:00")).date().isoformat(), "scheduled_session_start_fallback"
            except ValueError:
                pass
        raise DataUnavailable("Neither the actual local session date nor the scheduled date is available.")


def fastest_index(laps: dict) -> int:
    columns = ("time", "lap", "iacc", "del", "pin", "pout")
    if any(key not in laps for key in columns):
        raise DataUnavailable("Source lap metadata lacks timing or validity columns.")
    n = len(laps["time"])
    if any(len(laps[key]) != n for key in columns):
        raise DataUnavailable("Source lap metadata columns have inconsistent lengths.")
    candidates = [i for i, value in enumerate(laps["time"])
                  if isinstance(value, (int, float)) and not isinstance(value, bool)
                  and math.isfinite(value) and value > 0
                  and laps["iacc"][i] is True and laps["del"][i] is False
                  and laps["pin"][i] in (None, "None") and laps["pout"][i] in (None, "None")]
    if not candidates:
        raise DataUnavailable("No accurate, non-deleted flying lap with a valid lap time in this qualifying session.")
    return min(candidates, key=lambda i: laps["time"][i])


class SessionSource:
    def __init__(self, event: str):
        self.event = event
        self.id = session_id(event)
        self.directory = DATA / "raw" / self.id
        self.directory.mkdir(parents=True, exist_ok=True)
        self.records = []
        self.lock = threading.Lock()
        self.known = {}
        candidates = [DATA / "provenance" / f"{self.id}.json"]
        if self.id == "2024_bahrain_q":
            candidates.append(DATA / "provenance.json")
        for path in candidates:
            if path.exists():
                content = json.loads(path.read_text(encoding="utf-8"))
                if content.get("commit") == COMMIT:
                    self.known.update({item["local_file"]: item for item in content["files"]})

    def fetch(self, relative: str, filename: str):
        source_path = f"{self.event}/Qualifying/{relative}"
        url = f"{RAW_BASE}/{quote(source_path, safe='/')}"
        local = self.directory / filename
        local_relative = local.relative_to(ROOT).as_posix()
        sidecar = local.with_suffix(local.suffix + ".source.json")
        missing_marker = local.with_suffix(local.suffix + ".missing.json")
        if missing_marker.exists():
            missing = json.loads(missing_marker.read_text(encoding="utf-8"))
            if missing.get("url") == url and missing.get("status") == 404:
                raise DataUnavailable(missing["reason"])
        record = self.known.get(local_relative)
        if sidecar.exists():
            try:
                record = json.loads(sidecar.read_text(encoding="utf-8"))
            except ValueError:
                record = None
        payload = None
        if record and record.get("url") == url and local.exists():
            candidate = local.read_bytes()
            if hashlib.sha256(candidate).hexdigest() == record.get("sha256"):
                payload = candidate
        if payload is None:
            try:
                payload = request_bytes(url)
            except DataUnavailable as exc:
                reason = f"Source file '{relative}' is absent at the pinned repository commit (HTTP 404)."
                # A 404 for an immutable commit is stable. Cache this separately
                # from network errors so a completed season can rebuild offline.
                write_json(missing_marker, {"url": url, "status": 404, "reason": reason})
                raise DataUnavailable(reason) from exc
            try:
                json.loads(payload)
            except ValueError as exc:
                raise DownloadError("The source returned invalid JSON.") from exc
            temporary = local.with_suffix(local.suffix + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(local)
            record = {"url": url, "local_file": local_relative, "sha256": hashlib.sha256(payload).hexdigest(),
                      "bytes": len(payload)}
            write_json(sidecar, record)
        with self.lock:
            self.records.append(record)
        return json.loads(payload)


def load_driver(source: SessionSource, person: dict) -> dict:
    code = person["driver"]
    laps = source.fetch(f"{code}/laptimes.json", f"{code}_laptimes.json")
    index = fastest_index(laps)
    lap_number = int(laps["lap"][index])
    # Never silently choose a slower lap when the fastest lap's telemetry is absent.
    tel = source.fetch(f"{code}/{lap_number}_tel.json", f"{code}_{lap_number}_tel.json").get("tel", {})
    mandatory = ("time", "distance", "speed", "throttle", "brake")
    if any(key not in tel for key in mandatory):
        raise DataUnavailable(f"Fastest valid lap {lap_number} is missing required telemetry channels.")
    driver = {
        "code": code, "name": f"{person.get('fn', '')} {person.get('ln', '')}".strip() or code,
        "team": person.get("team", "Unknown"), "color": "#" + person.get("tc", "888888").lstrip("#"),
        "lap_time": laps["time"][index], "lap_number": lap_number,
        "qualifying_segment": laps.get("qs", [None] * len(laps["time"]))[index],
        "compound": laps.get("compound", [None] * len(laps["time"]))[index],
        "sectors": [laps.get(f"s{s}", [None] * len(laps["time"]))[index] for s in (1, 2, 3)],
        "telemetry": {key: tel[key] for key in (*mandatory, "x", "y") if key in tel},
    }
    try:
        clean = _clean_telemetry(driver)
    except (TypeError, ValueError) as exc:
        raise DataUnavailable(f"Fastest valid lap {lap_number} has unusable telemetry: {exc}") from exc
    if clean["time"].iloc[0] > 0.5 or clean["time"].iloc[-1] < driver["lap_time"] - 0.5:
        raise DataUnavailable(f"Fastest valid lap {lap_number} lacks telemetry at the start or end of the lap.")
    if clean["time"].diff().max() > 3:
        raise DataUnavailable(f"Fastest valid lap {lap_number} has a telemetry gap longer than 3 seconds.")
    return driver


def process_event(event: str) -> dict:
    source = SessionSource(event)
    metadata = source.fetch("drivers.json", "drivers.json").get("drivers", [])
    info = source.fetch("session_info.json", "session_info.json")
    if not metadata:
        raise DataUnavailable("No driver metadata in the source qualifying session.")
    drivers, unavailable = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(load_driver, source, person): person for person in metadata}
        for future in as_completed(futures):
            person = futures[future]
            try:
                drivers.append(future.result())
            except (DataUnavailable, DownloadError) as exc:
                unavailable.append({"code": person["driver"],
                                    "name": f"{person.get('fn', '')} {person.get('ln', '')}".strip(),
                                    "reason": str(exc),
                                    "kind": "download_error" if isinstance(exc, DownloadError) else "data_unavailable"})
    position = {person["driver"]: i for i, person in enumerate(metadata)}
    drivers.sort(key=lambda d: position[d["code"]])
    unavailable.sort(key=lambda d: position[d["code"]])
    date, date_basis = actual_session_date(info)
    session = {
        "id": source.id, "title": f"2024 {event.removesuffix(' Grand Prix')} · Qualifying",
        "year": 2024, "event": event, "session": "Qualifying", "date": date, "date_basis": date_basis,
        "source": "Bundled FastF1-derived data · TracingInsights",
        "source_url": f"https://github.com/{REPOSITORY}/tree/{COMMIT}/{quote(event, safe='')}/Qualifying",
        "source_commit": COMMIT, "selection": SELECTION,
        "expected_driver_count": len(metadata), "usable_driver_count": len(drivers),
        "unavailable_drivers": unavailable, "drivers": drivers,
    }
    write_json(DATA / f"{source.id}.json", session)
    provenance = {"repository": f"https://github.com/{REPOSITORY}", "commit": COMMIT,
                  "retrieved_at_utc": datetime.now(timezone.utc).isoformat(), "session_id": source.id,
                  "selection": SELECTION, "files": sorted(source.records, key=lambda r: r["local_file"]),
                  "transformation": "Retain fastest valid lap metadata and source time, distance, speed, throttle, brake, x, y arrays unchanged. Resampling occurs only at comparison time.",
                  "validation": "Usable telemetry spans the lap within 0.5 s at each end, without a gap longer than 3 s. Missing fastest telemetry is reported; no slower lap is silently substituted.",
                  "unavailable_drivers": unavailable, "license_file": "data/TRACINGINSIGHTS_LICENSE.txt"}
    write_json(DATA / "provenance" / f"{source.id}.json", provenance, pretty=True)
    if source.id == "2024_bahrain_q":
        write_json(DATA / "provenance.json", provenance, pretty=True)
    print(f"{event}: {len(drivers)}/{len(metadata)} drivers; {len(unavailable)} unavailable", flush=True)
    for person in unavailable:
        print(f"  {person['code']}: {person['kind']}: {person['reason']}", flush=True)
    return {key: session[key] for key in ("id", "event", "date", "date_basis", "expected_driver_count", "usable_driver_count", "unavailable_drivers")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", help="Optionally refresh one event, for example Bahrain (case-insensitive substring).")
    args = parser.parse_args(argv)
    DATA.mkdir(parents=True, exist_ok=True)
    source_index = DATA / "source_index_2024.json"
    if source_index.exists():
        tree = json.loads(source_index.read_text(encoding="utf-8-sig"))
    else:
        tree = json.loads(request_bytes(f"https://api.github.com/repos/{REPOSITORY}/git/trees/{COMMIT}"))
        write_json(source_index, tree, pretty=True)
    events = [item["path"] for item in tree["tree"] if item["type"] == "tree" and item["path"].endswith(" Grand Prix")]
    if len(events) != 24:
        raise RuntimeError(f"Expected 24 Grand Prix folders at the pinned commit; discovered {len(events)}.")
    selected = [event for event in events if not args.event or args.event.casefold() in event.casefold()]
    if args.event and len(selected) != 1:
        parser.error("--event must uniquely match one Grand Prix name.")
    failures = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(process_event, event): event for event in selected}
        for future in as_completed(futures):
            event = futures[future]
            try:
                future.result()
            except (DataUnavailable, DownloadError) as exc:
                failures.append({"event": event, "reason": str(exc),
                                 "kind": "download_error" if isinstance(exc, DownloadError) else "data_unavailable"})
                print(f"{event}: {type(exc).__name__}: {exc}", flush=True)
    sessions = []
    codes = set()
    for event in events:
        path = DATA / f"{session_id(event)}.json"
        if path.exists():
            record = json.loads(path.read_text(encoding="utf-8"))
            if "expected_driver_count" not in record:
                continue
            sessions.append({key: record[key] for key in ("id", "event", "date", "date_basis", "expected_driver_count", "usable_driver_count", "unavailable_drivers")})
            codes.update(d["code"] for d in record["drivers"])
            codes.update(d["code"] for d in record["unavailable_drivers"])
    sessions.sort(key=lambda s: s["date"])
    exclusions = [{"event": s["event"], "session_id": s["id"], **person}
                  for s in sessions for person in s["unavailable_drivers"] if person["kind"] == "data_unavailable"]
    errors = failures + [{"event": s["event"], "session_id": s["id"], **person}
                         for s in sessions for person in s["unavailable_drivers"] if person["kind"] == "download_error"]
    manifest = {
        "year": 2024, "scope": "All 24 Grand Prix Qualifying sessions; excludes practices, races and Sprint Qualifying.",
        "repository": f"https://github.com/{REPOSITORY}", "commit": COMMIT,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete": len(sessions) == 24 and not errors, "session_count": len(sessions),
        "expected_session_count": 24,
        "expected_driver_appearances": sum(s["expected_driver_count"] for s in sessions),
        "usable_driver_appearances": sum(s["usable_driver_count"] for s in sessions),
        "unique_driver_codes": sorted(codes), "unique_driver_count": len(codes),
        "exclusions": exclusions, "download_errors": errors, "sessions": sessions,
        "raw_source_bytes": sum(p.stat().st_size for p in (DATA / "raw").glob("*/*.json") if not p.name.endswith((".source.json", ".missing.json"))),
        "compact_session_bytes": sum((DATA / f"{s['id']}.json").stat().st_size for s in sessions),
    }
    write_json(DATA / "season_2024.json", manifest, pretty=True)
    print(json.dumps({k: v for k, v in manifest.items() if k not in ("sessions", "exclusions", "download_errors")}, indent=2), flush=True)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
