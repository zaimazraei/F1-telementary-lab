# Real 2024 qualifying data

The bundled dataset covers **all 24 Grand Prix qualifying sessions in 2024**,
with **474 usable driver laps** from **478 recorded qualifying entrants** and
**24 distinct drivers** across the season. These are real public telemetry
exports, not generated demonstration curves. Practice, race and Sprint
Qualifying sessions are outside this project's current scope.

Australia and the Netherlands each have 19 entrants in the source qualifying
driver list; the other 22 sessions have 20. All recorded entrants are either
selectable or explicitly listed as unavailable. Four entries cannot provide a
valid fastest-lap comparison under the selection rule:

| Session | Driver | Reason |
| --- | --- | --- |
| Emilia Romagna | Logan Sargeant (SAR) | No accurate, non-deleted flying lap with a valid lap time. |
| Saudi Arabia | Zhou Guanyu (ZHO) | No accurate, non-deleted flying lap with a valid lap time. |
| Monaco | Alexander Albon (ALB) | Fastest valid lap 28 (1:10.948) has no `ALB/28_tel.json` at the pinned source commit (HTTP 404). |
| Spain | Lance Stroll (STR) | Fastest valid lap 14 (1:12.372) has no `STR/14_tel.json` at the pinned source commit (HTTP 404). |

The missing telemetry is not replaced with a slower lap. No network errors
remained when the season was built. `season_2024.json` records all counts,
exclusions and session coverage. Its `complete` flag means all session/source
entries have been accounted for; it does not imply unavailable telemetry exists.

Displayed dates use the actual session start in circuit-local time, calculated
from the source UTC timing origin, actual session start offset and circuit UTC
offset. This correctly places postponed São Paulo qualifying on **3 November**
and Las Vegas qualifying on the local date **22 November**. Each session's
`date_basis` records this calculation; if actual timing is missing, an explicit
`scheduled_session_start_fallback` identifies use of the scheduled date.

Source: [TracingInsights/2024](https://github.com/TracingInsights/2024), which
exports Formula 1 timing and telemetry using FastF1. The exact source commit,
download URLs, retrieval time and SHA-256 hashes are in
`provenance/<session_id>.json`. `provenance.json` also contains the Bahrain
records for compatibility. `source_index_2024.json` retains the root Git tree
used to discover the 24 events at commit
`d1543a71370d9b617b627319f8ad80b2f85dfd5e`.
Unmodified downloaded source JSON is retained under `raw/<session_id>/`.
The upstream repository MIT license is retained as `TRACINGINSIGHTS_LICENSE.txt`.
The compact `2024_*_q.json` files retain the selected source arrays unchanged.
Raw source JSON totals 62,852,997 bytes; compact session files total about
21.5 MB. Per-source SHA-256 sidecars allow interrupted downloads to resume.

Selection: each driver's fastest accurate, non-deleted lap with no pit entry or
exit, across the complete qualifying session. Consequently **Leclerc's 1:29.165
is from Q2** while Verstappen's 1:29.179 is from Q3. This comparison is not the
final Q3 result or starting grid. The UI displays each lap's segment.

`python scripts/fetch_season.py` reproduces the full season using the pinned
commit. `python scripts/fetch_season.py --event Bahrain` refreshes one uniquely
matched event; `python scripts/fetch_sample.py` is a shortcut for Bahrain.
The first run requires an internet connection but no account. Cached raw files
are hash-verified and reused. Confirmed missing files at the immutable commit
are cached separately as HTTP 404 records, while temporary network failures
remain retryable. At most eight requests run at once. The downloader reads only
the public repository and never attempts to circumvent authenticated endpoints.

Each selected lap passes telemetry validation: required channels exist, usable
time samples reach within 0.5 seconds of each lap boundary, and no sample gap is
longer than 3 seconds. Drivers without qualifying telemetry are reported rather
than replaced with manufactured traces. The source data can still contain
sampling noise; validation does not make public telemetry exact.

For other events, the app can import qualifying directly with FastF1 after you
authenticate using its official command-line login. Imported records live in
`.cache/sessions/`; their underlying FastF1 cache is in `.cache/fastf1/`.

## Interpretation

The official lap and sector times are distinct from the approximate telemetry
delta. The delta uses shared integrated distance, a roughly 5 m display grid,
and elapsed time zeroed at the first shared distance. It is neither stretched
nor forced to match the official lap gap. Different integrated lap distances
can cause drift; for VER–LEC the trace ends around −0.183 s while the official
B-minus-A lap gap is −0.014 s. This is expected uncertainty, not a fabricated
timing correction. Twenty equal-distance sections are analytical bins, not
official timing sectors or exact corner boundaries. The public brake channel
is on/off and cannot be interpreted as brake pressure.
