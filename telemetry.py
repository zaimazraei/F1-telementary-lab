"""Load real qualifying laps and compare sampled telemetry on shared distance.

The official timing gap and the estimated distance-aligned delta are deliberately
separate quantities. Integrated speed distances vary between cars; these public
traces cannot establish exact corner-by-corner timing or causes of a time gain.
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / ".cache"
IMPORTED_DIR = CACHE_DIR / "sessions"
_IMPORT_LOCK = threading.Lock()
_SESSION_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")
AUTH_HELP = (
    "FastF1 needs an authenticated F1TV account with an eligible subscription. "
    "In the VS Code terminal, run: .\\.venv\\Scripts\\python.exe -m fastf1 auth f1tv --authenticate "
    "Then retry. The saved 2024 qualifying sessions work without login."
)


def _read_session(session_id: str) -> dict:
    if not isinstance(session_id, str) or not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Invalid session identifier.")
    for directory in (DATA_DIR, IMPORTED_DIR):
        path = directory / f"{session_id}.json"
        if path.is_file():
            stat = path.stat()
            session = _cached_session(str(path), stat.st_mtime_ns, stat.st_size)
            if session.get("id") == session_id and isinstance(session.get("drivers"), list):
                return session
    raise ValueError("Session not found. Select an available session or import one first.")


@lru_cache(maxsize=4)
def _cached_session(path: str, modified_ns: int, size: int) -> dict:
    """Reuse recent full sessions; a replaced or edited file gets a fresh key."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _driver_info(driver: dict) -> dict:
    return {key: driver.get(key) for key in (
        "code", "name", "team", "color", "lap_time", "lap_number", "qualifying_segment", "compound")}


@lru_cache(maxsize=128)
def _catalog_entry(path: str, modified_ns: int, size: int) -> dict | None:
    """Keep small metadata in memory rather than rereading a season of traces."""
    session = json.loads(Path(path).read_text(encoding="utf-8"))
    if "id" not in session or not isinstance(session.get("drivers"), list):
        return None
    info = {key: value for key, value in session.items() if key != "drivers"}
    info["drivers"] = [_driver_info(driver) for driver in session["drivers"]]
    return info


def get_catalog() -> dict:
    """Return only metadata; loading the dashboard never needs the network."""
    sessions = {}
    bundled = []
    for directory in (IMPORTED_DIR, DATA_DIR):
        for path in sorted(directory.glob("*.json")):
            try:
                stat = path.stat()
                info = _catalog_entry(str(path), stat.st_mtime_ns, stat.st_size)
                if info is None:
                    continue
                sessions[info["id"]] = info
                if directory == DATA_DIR and info["year"] == 2024:
                    bundled.append(info)
            except (OSError, ValueError, TypeError, KeyError):
                continue  # A half-written external file should not break the dashboard.
    codes = {driver["code"] for session in bundled
             for driver in session["drivers"] + session.get("unavailable_drivers", [])}
    summary = {
        "year": 2024, "session_count": len(bundled),
        "driver_lap_count": sum(len(session["drivers"]) for session in bundled),
        "unique_driver_count": len(codes),
        "unavailable_driver_count": sum(len(session.get("unavailable_drivers", [])) for session in bundled),
    }
    return {
        "sessions": sorted(sessions.values(), key=lambda s: (-s["year"], s.get("date") or "", s["event"])),
        "season_summary": summary,
    }


def _clean_telemetry(driver: dict) -> pd.DataFrame:
    """Validate physical channels, remove missing samples and duplicate distance."""
    frame = pd.DataFrame(driver["telemetry"])
    required = ["time", "distance", "speed", "throttle", "brake"]
    if not set(required).issubset(frame):
        raise ValueError(f"Incomplete telemetry for {driver['code']}.")
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna(subset=required)
    frame = frame.loc[(frame["time"] >= 0) & (frame["time"] <= driver["lap_time"] + 0.01)
                      & (frame["speed"] >= 0)]
    frame = frame.sort_values("time").drop_duplicates("time", keep="first")
    # Retain the first observation at any distance; discard a backward-distance
    # glitch instead of sorting it into a physically impossible time sequence.
    if len(frame):
        distance = frame["distance"].to_numpy()
        frame = frame.loc[np.r_[True, distance[1:] > np.maximum.accumulate(distance[:-1])]]
    if len(frame) < 20 or frame["distance"].iloc[-1] - frame["distance"].iloc[0] < 500:
        raise ValueError(f"Not enough usable full-lap telemetry for {driver['code']}.")
    frame["throttle"] = frame["throttle"].clip(0, 100)
    frame["brake"] = (frame["brake"] > 0).astype(int)
    return frame.reset_index(drop=True)


def _previous_sample(x: np.ndarray, xp: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Zero-order hold: brake is an on/off channel, never a blended pressure."""
    indices = np.searchsorted(xp, x, side="right") - 1
    return values[np.clip(indices, 0, len(values) - 1)]


def _stats(driver: dict, frame: pd.DataFrame) -> dict:
    info = _driver_info(driver)
    durations = np.diff(frame["time"].to_numpy())
    span = float(durations.sum())
    info.update({
        "top_speed": round(float(frame["speed"].max()), 1),
        "full_throttle_pct": round(float(np.dot(durations, frame["throttle"].to_numpy()[:-1] >= 98) / span * 100), 1),
        "braking_pct": round(float(np.dot(durations, frame["brake"].to_numpy()[:-1]) / span * 100), 1),
    })
    return info


def compare_laps(session_id: str, driver_a: str, driver_b: str) -> dict:
    """Return JSON-ready chart data; positive B-minus-A delta means A is ahead."""
    if driver_a == driver_b:
        raise ValueError("Select two different drivers.")
    session = _read_session(session_id)
    by_code = {d["code"]: d for d in session["drivers"]}
    if driver_a not in by_code or driver_b not in by_code:
        raise ValueError("A selected driver has no usable lap in this session.")
    a, b = by_code[driver_a], by_code[driver_b]
    fa, fb = _clean_telemetry(a), _clean_telemetry(b)
    start = max(float(fa["distance"].iloc[0]), float(fb["distance"].iloc[0]))
    end = min(float(fa["distance"].iloc[-1]), float(fb["distance"].iloc[-1]))
    if end - start < 500:
        raise ValueError("The selected laps do not share enough distance to compare.")
    # 5 m is a display grid, not the sensor resolution. No extrapolation, distance
    # normalization, endpoint forcing, or smoothing is applied.
    grid = np.linspace(start, end, int(np.ceil((end - start) / 5)) + 1)
    tel = {"distance": np.round(grid, 3).tolist()}
    elapsed = {}
    for label, frame in (("a", fa), ("b", fb)):
        distance = frame["distance"].to_numpy()
        for channel in ("speed", "throttle"):
            tel[f"{channel}_{label}"] = np.round(np.interp(grid, distance, frame[channel]), 3).tolist()
        tel[f"brake_{label}"] = _previous_sample(grid, distance, frame["brake"].to_numpy()).astype(int).tolist()
        elapsed[label] = np.interp(grid, distance, frame["time"])
        elapsed[label] -= elapsed[label][0]
        tel[f"elapsed_{label}"] = np.round(elapsed[label], 6).tolist()
    delta = elapsed["b"] - elapsed["a"]
    tel["delta"] = np.round(delta, 6).tolist()
    lap_delta = round(float(b["lap_time"] - a["lap_time"]), 6)
    boundaries = np.linspace(start, end, 21)
    boundary_delta = np.interp(boundaries, grid, delta)
    minis = []
    for i, gain in enumerate(np.diff(boundary_delta)):
        minis.append({"index": i + 1, "start": round(float(boundaries[i]), 2),
                      "end": round(float(boundaries[i + 1]), 2), "gain": round(float(gain), 6),
                      "winner": driver_a if gain > 0.0005 else driver_b if gain < -0.0005 else "TIE"})
    sectors = []
    accumulated_a = 0.0
    for i, (sa, sb) in enumerate(zip(a.get("sectors", []), b.get("sectors", []))):
        if not isinstance(sa, (int, float)) or not isinstance(sb, (int, float)):
            continue
        accumulated_a += sa
        sectors.append({"name": f"S{i + 1}", "time_a": sa, "time_b": sb,
                        "delta": round(sb - sa, 6),
                        "end_distance": round(float(np.interp(accumulated_a, fa["time"], fa["distance"])), 2)})
    track = None
    if {"x", "y"}.issubset(fa.columns) and fa[["x", "y"]].notna().all().all():
        track = {"distance": tel["distance"],
                 "x": np.round(np.interp(grid, fa["distance"], fa["x"]), 3).tolist(),
                 "y": np.round(np.interp(grid, fa["distance"], fa["y"]), 3).tolist()}
    faster = driver_a if lap_delta > 0 else driver_b
    insights = [f"{faster}'s selected lap is {abs(lap_delta):.3f} s quicker by official lap timing. "
                "Each driver contributes their fastest valid lap across qualifying."]
    if a.get("qualifying_segment") != b.get("qualifying_segment"):
        insights.append(f"These laps come from different qualifying segments: {driver_a} {a.get('qualifying_segment') or 'unknown'} "
                        f"and {driver_b} {b.get('qualifying_segment') or 'unknown'}. Track conditions can differ.")
    for code, segment in ((driver_a, max(minis, key=lambda m: m["gain"])),
                          (driver_b, min(minis, key=lambda m: m["gain"]))):
        signed_gain = segment["gain"] if code == driver_a else -segment["gain"]
        if signed_gain > 0:
            insights.append(f"{code}'s largest estimated gain is {signed_gain:.3f} s between "
                            f"{segment['start']:.0f} and {segment['end']:.0f} m. Zoom into that range to compare braking and speed.")
    insights.append(f"The sampled delta ends at {delta[-1]:+.3f} s; the official B-minus-A gap is {lap_delta:+.3f} s. "
                    "Distance integration and the shared coverage limit explain why these need not match.")
    methodology = [
        "Fastest accurate, non-deleted flying lap across Q1/Q2/Q3; this is not a comparison of final grid positions.",
        "Distance is integrated from speed and differs slightly between drivers. Only the overlapping distance range is shown.",
        "Speed, throttle and elapsed time are linearly interpolated onto a roughly 5 m display grid. This does not add sensor precision.",
        "Brake is an on/off state, held until the next sample; it does not measure brake pressure. Throttle is clipped to 0–100%.",
        "Each elapsed trace is zeroed at the first shared distance. Delta = elapsed B − elapsed A; a positive value means A is ahead of B since that point.",
        "The delta is an estimate, not official timing. It is not forced to match the official lap gap. The 20 equal-distance sections are not official timing sectors.",
        "Top speed uses available samples. Full-throttle (≥98%) and braking percentages are weighted by sampled time across each lap.",
        "Telemetry describes associations; fuel, tyres, setup, traffic, track evolution and sampling can influence differences. It does not prove driver technique caused a gain.",
    ]
    return {"session": {k: v for k, v in session.items() if k != "drivers"},
            "drivers": {"a": _stats(a, fa), "b": _stats(b, fb)}, "telemetry": tel,
            "lap_delta": lap_delta, "sectors": sectors, "mini_sectors": minis,
            "track": track, "insights": insights, "methodology": methodology,
            "coverage": {"start": start, "end": end, "trace_end_delta": float(delta[-1])}}


def import_fastf1(year: int, event: str) -> str:
    """Download qualifying once, then save a compact local session.

    Authentication is performed separately in the user's terminal. The pinned
    FastF1 3.9.2 token manager is inspected without exposing the token, and its
    renewal callback is temporarily disabled so a web job can never prompt.
    """
    if isinstance(year, bool) or not isinstance(year, int) or not 2018 <= year <= datetime.now().year:
        raise ValueError("Choose a season from 2018 through the current year.")
    if not isinstance(event, str) or not event.strip() or len(event) > 100:
        raise ValueError("Enter an event name, for example Bahrain or Monza.")
    import fastf1
    from fastf1.exceptions import F1AuthError
    from fastf1.internals.f1account import token_manager

    with _IMPORT_LOCK:
        # Reload from the CLI's token file if a prior attempt read an expired
        # token; do not clear or alter the user's persisted credentials.
        token_manager._token = None
        stored = token_manager.get_stored()
        if stored is None or not stored.is_valid():
            raise RuntimeError(AUTH_HELP)

        def no_interactive_login():
            raise F1AuthError(AUTH_HELP)

        original_login = token_manager._default_auth_func
        token_manager._default_auth_func = no_interactive_login
        try:
            fastf1_cache = CACHE_DIR / "fastf1"
            fastf1_cache.mkdir(parents=True, exist_ok=True)
            fastf1.Cache.configure(cache_dir=str(fastf1_cache), force_renew=False)
            session = fastf1.get_session(year, event.strip(), "Q")
            # Race-control messages carry lap deletions; load them before
            # pick_not_deleted so cancelled laps cannot enter the comparison.
            session.load(laps=True, telemetry=True, weather=False, messages=True)
            laps = session.laps.pick_accurate().pick_not_deleted().pick_wo_box()
            segments = {}
            for number, segment in enumerate(session.laps.split_qualifying_sessions(), 1):
                if segment is not None:
                    segments.update({index: f"Q{number}" for index in segment.index})
            drivers = []
            for code in sorted(laps["Driver"].dropna().unique()):
                fastest = laps.pick_drivers(code).pick_fastest(only_by_time=True)
                if fastest is None or pd.isna(fastest["LapTime"]):
                    continue
                try:
                    telemetry = fastest.get_telemetry()
                    person = session.get_driver(code)
                    channels = {"time": telemetry["Time"].dt.total_seconds().tolist(),
                                **{to: telemetry[fr].tolist() for to, fr in (
                                    ("distance", "Distance"), ("speed", "Speed"), ("throttle", "Throttle"),
                                    ("brake", "Brake"), ("x", "X"), ("y", "Y"))}}
                    driver = {"code": str(code), "name": str(person["FullName"]),
                              "team": str(person["TeamName"]), "color": "#" + str(person["TeamColor"]),
                              "lap_time": float(fastest["LapTime"].total_seconds()),
                              "lap_number": int(fastest["LapNumber"]), "qualifying_segment": segments.get(fastest.name),
                              "compound": str(fastest["Compound"]),
                              "sectors": [None if pd.isna(fastest[f"Sector{i}Time"]) else float(fastest[f"Sector{i}Time"].total_seconds()) for i in (1, 2, 3)],
                              "telemetry": channels}
                    clean = _clean_telemetry(driver)
                    driver["telemetry"] = json.loads(clean.to_json(orient="list"))
                    drivers.append(driver)
                except (ValueError, KeyError, TypeError):
                    continue
            if len(drivers) < 2:
                raise RuntimeError("FastF1 returned fewer than two valid full laps. Check authentication and whether the session has finished.")
            event_name = str(session.event["EventName"])
            slug = re.sub(r"[^a-z0-9]+", "_", event_name.lower()).strip("_")
            session_id = f"{year}_{slug}_q"
            record = {"id": session_id, "title": f"{year} {event_name} · Qualifying", "year": year,
                      "event": event_name, "session": "Qualifying", "date": str(session.date.date()),
                      "source": f"FastF1 {fastf1.__version__} · downloaded and cached locally",
                      "source_url": "https://docs.fastf1.dev/", "drivers": drivers,
                      "selection": "Fastest accurate, non-deleted flying lap across Q1/Q2/Q3 for each driver."}
            IMPORTED_DIR.mkdir(parents=True, exist_ok=True)
            temporary = IMPORTED_DIR / f"{session_id}.tmp"
            temporary.write_text(json.dumps(record, allow_nan=False, separators=(",", ":")), encoding="utf-8")
            temporary.replace(IMPORTED_DIR / f"{session_id}.json")
            return session_id
        finally:
            token_manager._default_auth_func = original_login
