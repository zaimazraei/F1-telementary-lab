# F1 Telemetry Lab

A local Python project that answers: **where does one driver gain time on another?**

Compare two drivers' fastest valid qualifying laps with interactive speed, throttle, brake, time-delta and track charts. The saved archive covers the 2024 season's Grand Prix qualifying sessions and considers every listed driver. It works offline after installation.

The dashboard shows the number of saved sessions, distinct drivers and usable selected laps. Choose a race from the dated session list, then two drivers. If a driver has no valid full-lap telemetry, the session's expandable coverage note explains the gap. Missing telemetry is never generated or filled with another driver's data.

The verified collection has **24 sessions, 24 distinct drivers and 474 selected laps**, covering 478 driver-session entries in the source. Australia and the Netherlands each list 19 entrants. Four entries are unavailable under the project's selection rule:

| Event | Driver | Reason |
| --- | --- | --- |
| Saudi Arabia | Guanyu Zhou | No accurate, non-deleted flying lap with a valid time |
| Emilia Romagna | Logan Sargeant | No accurate, non-deleted flying lap with a valid time |
| Monaco | Alexander Albon | Selected fastest-lap telemetry is missing from the pinned source |
| Spain | Lance Stroll | Selected fastest-lap telemetry is missing from the pinned source |

The collection uses about **84 MB** for original source JSON and compact session files, excluding Python dependencies and small provenance records. No network download errors remain.

This archive stores **one fastest valid lap per driver per Grand Prix qualifying session where full-lap telemetry is available**, together with each driver's original lap-timing records. It does not contain practice, race or sprint-qualifying sessions, or telemetry for every attempt. The selected lap may be from Q1, Q2 or Q3. If the fastest valid lap has unusable telemetry, the driver is reported as unavailable; a slower lap is not silently substituted.

To rebuild or resume the archive from its fixed public source version:

```powershell
.\.venv\Scripts\python.exe scripts\fetch_season.py
```

To refresh just one event, add `--event Bahrain` (or another unique event-name substring). Verified raw files are reused. Download errors are recorded separately from missing or unusable source data in `data/season_2024.json`.

## Open in VS Code and run

Open this **f1-telemetry-lab** folder in VS Code (File → Open Folder). The project has its own `.venv` Python environment and VS Code settings.

Your environment is already installed. In the VS Code PowerShell terminal:

```powershell
.\.venv\Scripts\python.exe app.py
```

Open **http://127.0.0.1:8050** in your browser. Leave the terminal running; press **Ctrl+C** to stop the server. You can also double-click `start.bat`, or use the **F1 Telemetry Lab** Run and Debug configuration with the VS Code Python and Python Debugger extensions installed.

If the terminal says the port is already in use, the app may already be running: open the URL first. To use a different port:

```powershell
$env:PORT = '8051'
.\.venv\Scripts\python.exe app.py
```

On a fresh Windows installation with Python 3.11 or newer, run `setup.bat` once, then `start.bat`. The tested interpreter is Python 3.13. The setup uses `requirements-lock.txt` for reproducibility. `requirements.txt` lists the main dependencies for development.

## Explore the dashboard

1. Choose a session and two different drivers, then compare their laps.
2. Hover over the plots for values. Drag horizontally to inspect a shorter part of the lap; reset the zoom to see the full lap again.
3. Compare the speed curves with the throttle and brake traces around that distance.
4. Read the time-delta trace and distance-segment gains to identify where the advantage changes.
5. Use the official sector table to check the broad pattern against recorded timing.
6. Export the aligned telemetry as CSV to explore it with pandas, Excel or a notebook.

**Delta = driver B elapsed time − driver A elapsed time.** A positive value means A reaches that distance sooner. An upward-moving trace means A gains time in that interval. A driver can gain in an interval while still being behind overall. Swapping drivers reverses the sign.

## Load another session with FastF1

The dashboard's FastF1 import accepts a season and event name, such as `2024` and `Monza`. It loads qualifying, selects each driver's fastest accurate, non-deleted flying lap and saves the data under `.cache/sessions/`. First downloads can take several minutes; later requests benefit from the local `.cache/fastf1` cache.

As of FastF1 3.9, upstream Formula 1 data can require an F1TV Access account or higher. If prompted by the app, **sign in yourself in the VS Code terminal**:

```powershell
.\.venv\Scripts\python.exe -m fastf1 auth f1tv --authenticate
```

Then retry the dashboard import. Enter credentials only in FastF1's own local sign-in flow. The dashboard does not collect passwords. Authentication requirements are documented in the [FastF1 release notes](https://github.com/theOehrly/Fast-F1/releases/tag/v3.9.0). The saved 2024 archive needs no account.

## What the calculations can tell you

- **Lap choice:** fastest valid lap across the entire qualifying session. Drivers may set those laps in different segments (Q1, Q2, Q3); the driver cards show the segment where known. This is not a Q3-only ranking. For example, Leclerc's fastest bundled lap is from Q2.
- **Official timing:** lap and sector times come from recorded timing. The official lap-time gap is shown separately from the telemetry-derived delta.
- **Alignment:** telemetry is compared on a shared distance grid only over the two laps' overlapping distance range. Speed, throttle and elapsed time are interpolated; the brake channel is sampled as a step signal.
- **Precision:** distance is estimated from telemetry. Different driven paths, sampling and integrated-distance drift mean that equal distance does not guarantee exactly the same physical position. The delta is approximate and is not forced to equal the official finishing gap.
- **Distance segments:** equal-distance bins show the change in delta within each bin. They are not official timing sectors or named corners.
- **Pedals:** throttle is a percentage. Brake is on/off, **not brake pressure**. Full-throttle (at least 98%) and braking percentages are weighted by sampled time across each selected lap.
- **Track map:** positional telemetry gives an approximate trace, not a surveyed circuit map.
- **Interpretation:** different track conditions, tyres, traffic, setup and qualifying phases can affect the result. These plots show differences; they do not establish their cause or isolate driver skill.

The project uses observations, interpolation and descriptive statistics. It does not train a machine learning model.

## Source files to learn from

| File | Purpose |
| --- | --- |
| `app.py` | Flask routes, background import jobs and CSV export |
| `telemetry.py` | pandas/NumPy data preparation, interpolation, delta calculations and FastF1 import |
| `templates/index.html` | Dashboard structure |
| `static/styles.css` | Dashboard appearance and responsive layout |
| `static/app.js` | Driver selection, API requests and interactive Plotly charts |
| `scripts/fetch_season.py` | Rebuild the 2024 qualifying archive from the pinned public source |
| `scripts/fetch_sample.py` | Rebuild Bahrain qualifying for all listed drivers |
| `scripts/bundle_plotly.py` | Copy Plotly's JavaScript locally for offline charts |
| `data/season_2024.json` | Season coverage, exclusions and download status |
| `data/provenance/` | Per-session source URLs, upstream commit and file hashes |
| `data/provenance.json` | Compatibility source record for Bahrain |
| `data/raw/` | Original source files, organized by qualifying session |
| `tests/` | Numerical and HTTP API checks |

A useful reading order is `app.py` → `telemetry.py` → `static/app.js`. Start by changing the number of distance segments or one chart label, then rerun and compare the result.

## Verification

Run the automated checks without downloading any session:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The bundled data and offline comparison are testable without an F1 account. Importing a new upstream session additionally depends on your network, FastF1 account access and that session's available telemetry.

## Data attribution

The saved archive comes from [TracingInsights/2024](https://github.com/TracingInsights/2024), a public FastF1-derived dataset. The exact source commit, URLs, download hashes and transformation are recorded in `data/provenance/`. Its MIT license is retained in `data/TRACINGINSIGHTS_LICENSE.txt`.

Charts use [Plotly](https://github.com/plotly/plotly.js), whose license notice is retained in the bundled JavaScript. This is an independent educational project, not an official Formula 1 product.
