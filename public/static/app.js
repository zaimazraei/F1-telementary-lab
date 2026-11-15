/* Local-only dashboard. All traces come from the Python comparison API. */
"use strict";
const $ = (id) => document.getElementById(id);
const COLORS = {a: "#168c81", b: "#8571c3", grid: "#e9ebe1", text: "#87907c"};
const state = {sessions: [], comparison: null, syncing: false, request: 0, busy: false};
const chartIds = ["speed-chart", "delta-chart", "throttle-chart", "brake-chart"];
const fmt = (n, digits = 1) => Number.isFinite(Number(n)) ? Number(n).toFixed(digits) : "—";

function lapTime(n) { if (n === null || n === undefined || !Number.isFinite(Number(n))) return "—"; return `${Math.floor(n / 60)}:${(n % 60).toFixed(3).padStart(6, "0")}`; }
function esc(value) { return String(value ?? "").replace(/[&<>"']/g, (ch) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[ch])); }
function errorMessage(error) { return error?.message || "Something went wrong. Please try again."; }
async function api(url, options) { const response = await fetch(url, options); let data; try { data = await response.json(); } catch { throw new Error("The local server returned an unexpected response. Check the server or deployment logs."); } if (!response.ok) throw new Error(data.error || data.message || `Request failed (${response.status}).`); return data; }
function showError(message) { $("error-banner").textContent = message; $("error-banner").hidden = !message; }
function selectedQuery() { return new URLSearchParams({session: $("session-select").value, driver_a: $("driver-a-select").value, driver_b: $("driver-b-select").value}).toString(); }
function busy(value) { state.busy = value; ["compare-button", "swap-button", "session-select", "driver-a-select", "driver-b-select"].forEach((id) => $(id).disabled = value); $("compare-button").innerHTML = value ? "Comparing…" : "Compare laps <span>↗</span>"; $("results").classList.toggle("is-loading", value); $("export-button").disabled = value || !state.comparison; }

async function loadCatalog(preferredId) {
  const activeId = $("session-select").value;
  const data = await api("/api/catalog"); state.sessions = data.sessions || [];
  if (!state.sessions.length) throw new Error("No sessions are available yet. Add a sample dataset or import a session with FastF1.");
  // Sessions are chronological within a season, independent of source order.
  state.sessions.sort((a, b) => Number(b.year) - Number(a.year) || String(a.date || a.session_date || "9999").localeCompare(String(b.date || b.session_date || "9999")) || String(a.event).localeCompare(String(b.event)));
  $("session-select").innerHTML = state.sessions.map((s) => `<option value="${esc(s.id)}">${esc(sessionLabel(s))}</option>`).join("");
  const bahrainId = state.sessions.find((s) => Number(s.year) === 2024 && /bahrain/i.test(`${s.event} ${s.id}`))?.id;
  const selectedId = [preferredId, activeId, bahrainId].find((id) => id && state.sessions.some((s) => s.id === id));
  if (selectedId) $("session-select").value = selectedId;
  renderSeasonCoverage(data.season_summary);
  populateDrivers();
}
function sessionLabel(session) {
  const title = session.title || `${session.year} ${session.event} · ${session.session || "Qualifying"}`;
  const rawDate = session.date || session.session_date;
  if (!rawDate || !/^\d{4}-\d{2}-\d{2}/.test(rawDate)) return title;
  const date = new Date(`${rawDate.slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(date.getTime())) return title;
  const label = new Intl.DateTimeFormat("en-GB", {day: "2-digit", month: "short", timeZone: "UTC"}).format(date);
  return `${title} · ${label}`;
}
function renderSeasonCoverage(summary) {
  const element = $("season-coverage");
  if (!summary || !Number.isFinite(Number(summary.session_count))) { element.hidden = true; return; }
  const parts = [`<span class="coverage-year">${esc(summary.year || "SAVED")} SEASON</span>`, `<span><strong>${Number(summary.session_count)}</strong> sessions</span>`];
  if (Number.isFinite(Number(summary.unique_driver_count))) parts.push(`<span><strong>${Number(summary.unique_driver_count)}</strong> drivers</span>`);
  if (Number.isFinite(Number(summary.driver_lap_count))) parts.push(`<span><strong>${Number(summary.driver_lap_count)}</strong> qualifying laps</span>`);
  parts.push(`<span class="coverage-local"><span class="status-dot"></span> ${document.body.dataset.hosted === "true" ? "Saved dataset" : "Saved locally"}</span>`);
  element.innerHTML = parts.join('<span class="coverage-divider" aria-hidden="true">·</span>');
  element.hidden = false;
  const unavailable = Number(summary.unavailable_driver_count);
  element.title = unavailable > 0 ? `${unavailable} driver-session entries have no usable qualifying lap; reasons are listed for each affected session.` : "Saved qualifying telemetry is available without an internet connection.";
}
function renderAvailability(session) {
  const missing = Array.isArray(session?.unavailable_drivers) ? session.unavailable_drivers : [];
  const note = $("session-availability");
  note.hidden = missing.length === 0;
  note.open = false;
  if (!missing.length) { $("unavailable-drivers").innerHTML = ""; return; }
  const available = session.usable_driver_count ?? session.drivers?.length ?? 0;
  const entrants = session.expected_driver_count ?? session.entrant_count ?? available + missing.length;
  $("availability-summary").textContent = `${available} of ${entrants} drivers available · ${missing.length} without a usable qualifying lap`;
  $("unavailable-drivers").innerHTML = missing.map((driver) => `<li><strong>${esc(driver.name || driver.code)}${driver.name && driver.code ? ` (${esc(driver.code)})` : ""}</strong> — ${esc(driver.reason || "No usable qualifying telemetry is available.")}</li>`).join("");
}
function populateDrivers() {
  const session = state.sessions.find((s) => s.id === $("session-select").value);
  const drivers = session?.drivers || [];
  const previousA = $("driver-a-select").value, previousB = $("driver-b-select").value;
  const options = drivers.map((d) => `<option value="${esc(d.code)}">${esc(d.name || d.code)}</option>`).join("");
  $("driver-a-select").innerHTML = options; $("driver-b-select").innerHTML = options;
  $("driver-a-select").value = drivers.some((d) => d.code === previousA) ? previousA : drivers.find((d) => d.code === "VER")?.code || drivers[0]?.code || "";
  $("driver-b-select").value = drivers.some((d) => d.code === previousB && d.code !== $("driver-a-select").value) ? previousB : drivers.find((d) => d.code === "LEC" && d.code !== $("driver-a-select").value)?.code || drivers.find((d) => d.code !== $("driver-a-select").value)?.code || "";
  renderAvailability(session);
}
async function compare() {
  if ($("driver-a-select").value === $("driver-b-select").value) { showError("Choose two different drivers to compare their laps."); return; }
  const request = ++state.request; busy(true); showError("");
  try {
    const data = await api(`/api/compare?${selectedQuery()}`); if (request !== state.request) return;
    state.comparison = data; $("results").hidden = false; $("loading-state").hidden = true;
    await render(data);
  } catch (error) { showError(errorMessage(error)); $("loading-state").hidden = true; }
  finally { if (request === state.request) busy(false); }
}
function driverCard(driver, key) {
  const card = $("driver-card-" + key); card.style.setProperty("--card-color", COLORS[key]);
  card.innerHTML = `<div class="driver-top"><span class="driver-code">${esc(driver.code)}</span><div><h3>${esc(driver.name || driver.code)}</h3><div class="driver-team">${esc(driver.team || "Qualifying")}</div></div></div><div class="lap-time-row"><strong class="lap-time">${lapTime(driver.lap_time)}</strong><span class="lap-label">${esc(driver.qualifying_segment || "Q")} · LAP ${esc(driver.lap_number ?? "—")}</span></div><div class="driver-stats"><div><span>TOP SPEED</span><strong>${fmt(driver.top_speed, 0)} <small>km/h</small></strong></div><div title="Throttle at least 98%, weighted by sampled lap time"><span>FULL THROTTLE</span><strong>${fmt(driver.full_throttle_pct, 0)}<small>% time</small></strong></div><div title="Brake-on share, weighted by sampled lap time"><span>BRAKING</span><strong>${fmt(driver.braking_pct, 0)}<small>% time</small></strong></div></div>`;
}
function legend(a, b) { return `<span><i class="legend-line" style="background:${COLORS.a}"></i>${esc(a.code)}</span><span><i class="legend-line" style="background:${COLORS.b}"></i>${esc(b.code)}</span>`; }
function chartLayout(height, yaxis = {}, extra = {}) {
  return {height, margin: {l: 47, r: 22, t: 12, b: 33}, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", font: {family: '"Cascadia Code", Consolas, monospace', size: 9, color: COLORS.text}, showlegend: false, hovermode: "x unified", dragmode: "zoom", hoverlabel: {bgcolor: "#fffefa", bordercolor: "#dedfd6", font: {family: '"Segoe UI", sans-serif', size: 11, color: "#333c2e"}}, xaxis: {gridcolor: COLORS.grid, zeroline: false, ticks: "", tickformat: ",.0f", nticks: 7, fixedrange: false, title: {text: "", standoff: 8}}, yaxis: {gridcolor: COLORS.grid, zeroline: false, ticks: "", nticks: 5, fixedrange: true, ...yaxis}, ...extra};
}
const chartConfig = {responsive: true, displayModeBar: false, scrollZoom: false, displaylogo: false};
function line(x, y, name, color, suffix, shape = "linear") { return {x, y, name, type: "scatter", mode: "lines", line: {color, width: 1.8, shape}, hovertemplate: `%{y:.1f}${suffix}<extra>${esc(name)}</extra>`}; }
async function render(data) {
  const {a, b} = data.drivers, t = data.telemetry;
  driverCard(a, "a"); driverCard(b, "b");
  const winner = data.lap_delta > 0 ? a : b;
  $("gap-card").innerHTML = `<p class="section-number">THE OFFICIAL LAP DIFFERENCE</p><div class="gap-time">${fmt(Math.abs(data.lap_delta), 3)}<small>s</small></div><p class="gap-result">${data.lap_delta === 0 ? "Identical recorded lap times" : `<strong>${esc(winner.name || winner.code)}</strong> is quicker`}</p><p class="gap-caption">Fastest available valid qualifying laps</p>`;
  $("data-status").textContent = `${data.session.title || `${data.session.year} ${data.session.event} · Qualifying`} · ${data.session.source || "Saved telemetry"}`;
  $("circuit-name").textContent = data.session.event || "The racing line";
  $("speed-legend").innerHTML = legend(a, b);
  $("distance-stat").textContent = `${fmt((t.distance.at(-1) - t.distance[0]) / 1000, 2)} km`;
  $("delta-key").innerHTML = `<span><strong style="color:${COLORS.a}">＋ ${esc(a.code)} ahead</strong></span><span><strong style="color:${COLORS.b}">− ${esc(b.code)} ahead</strong></span><span>B elapsed − A elapsed · seconds</span>`;
  $("gain-legend").innerHTML = `<span style="color:${COLORS.a}">${esc(a.code)}</span> / <span style="color:${COLORS.b}">${esc(b.code)}</span> gains locally`;
  renderMiniSectors(data); renderSectors(data); renderNotes(data);
  const speedHeight = $("speed-chart").clientHeight || 270, deltaHeight = $("delta-chart").clientHeight || 220, pedalHeight = $("throttle-chart").clientHeight || 225;
  const extent = [t.distance[0], t.distance.at(-1)];
  const layouts = [chartLayout(speedHeight, {ticksuffix: "", range: [Math.max(0, Math.floor(Math.min(...t.speed_a, ...t.speed_b) / 50) * 50 - 10), Math.ceil(Math.max(...t.speed_a, ...t.speed_b) / 50) * 50 + 5]}), chartLayout(deltaHeight, {tickformat: "+.2f", zeroline: true, zerolinecolor: "#adb6a0", zerolinewidth: 1}), chartLayout(pedalHeight, {range: [-4, 105], tickvals: [0, 50, 100]}, {margin: {l: 45, r: 22, t: 12, b: 37}}), chartLayout(pedalHeight, {range: [-.12, 1.25], tickvals: [0, 1], ticktext: ["OFF", "ON"]}, {margin: {l: 45, r: 22, t: 12, b: 37}})];
  layouts.forEach((l) => l.xaxis.range = extent);
  const deltaA = t.delta.map((v) => Math.max(0, v)), deltaB = t.delta.map((v) => Math.min(0, v));
  const traces = [
    [line(t.distance,t.speed_a,a.code,COLORS.a," km/h"),line(t.distance,t.speed_b,b.code,COLORS.b," km/h")],
    [{...line(t.distance,deltaA,`${a.code} advantage`,COLORS.a," s"),fill:"tozeroy",fillcolor:"rgba(22,140,129,.09)",hoverinfo:"skip",hovertemplate:undefined,line:{width:0}}, {...line(t.distance,deltaB,`${b.code} advantage`,COLORS.b," s"),fill:"tozeroy",fillcolor:"rgba(133,113,195,.09)",hoverinfo:"skip",hovertemplate:undefined,line:{width:0}}, {...line(t.distance,t.delta,`${b.code} − ${a.code}`,"#4e6050"," s"),hovertemplate:"%{y:+.3f} s<extra>Estimated gap</extra>"}],
    [line(t.distance,t.throttle_a,a.code,COLORS.a,"%"),line(t.distance,t.throttle_b,b.code,COLORS.b,"%")],
    [line(t.distance,t.brake_a,a.code,COLORS.a,"","hv"),line(t.distance,t.brake_b,b.code,COLORS.b,"","hv")]
  ];
  await Promise.all(chartIds.map((id, i) => Plotly.react(id, traces[i], layouts[i], chartConfig)));
  chartIds.forEach((id) => { const chart = $(id); if (!chart.dataset.linked) { chart.on("plotly_relayout", (event) => linkZoom(id, event)); chart.dataset.linked = "true"; } });
  await renderTrack(data);
}
async function linkZoom(source, event) {
  if (state.syncing || (!Object.hasOwn(event, "xaxis.range[0]") && !event["xaxis.autorange"])) return;
  state.syncing = true;
  const update = event["xaxis.autorange"] ? {"xaxis.autorange": true} : {"xaxis.range": [event["xaxis.range[0]"], event["xaxis.range[1]"]]};
  try { await Promise.all(chartIds.filter((id) => id !== source).map((id) => Plotly.relayout(id, update))); } finally { state.syncing = false; }
}
function renderMiniSectors(data) {
  const a = data.drivers.a, b = data.drivers.b;
  $("mini-sectors").innerHTML = (data.mini_sectors || []).map((s, i) => { const isA = Number(s.gain) > 0, driver = isA ? a : b, color = Math.abs(s.gain) < .0005 ? "#a5ad9a" : COLORS[isA ? "a" : "b"]; return `<button class="mini-sector" style="background:${color}" data-start="${Number(s.start)}" data-end="${Number(s.end)}" title="${fmt(s.start,0)}–${fmt(s.end,0)} m: ${esc(driver.code)} gains ${fmt(Math.abs(s.gain),3)} s. Click to zoom." aria-label="Segment ${i+1}, ${esc(driver.code)} gains ${fmt(Math.abs(s.gain),3)} seconds; zoom to segment">${i+1}</button>`; }).join("");
}
function renderSectors(data) {
  $("sector-driver-a").textContent = data.drivers.a.code; $("sector-driver-b").textContent = data.drivers.b.code;
  $("sector-rows").innerHTML = (data.sectors || []).length ? data.sectors.map((s) => { const gap = s.delta ?? Number(s.time_b)-Number(s.time_a), code = gap >= 0 ? data.drivers.a.code : data.drivers.b.code; return `<tr><td>${esc(s.name)}</td><td>${s.time_a == null ? "—" : fmt(s.time_a,3)}</td><td>${s.time_b == null ? "—" : fmt(s.time_b,3)}</td><td><span class="advantage" style="color:${gap>=0 ? COLORS.a : COLORS.b}">${gap === 0 ? "Equal" : `${esc(code)} · ${fmt(Math.abs(gap),3)}s`}</span></td></tr>`; }).join("") : '<tr><td colspan="4">Official sector timing is unavailable for this snapshot.</td></tr>';
}
function renderNotes(data) {
  $("insights").innerHTML = (data.insights || []).map((text) => `<li>${esc(text)}</li>`).join("");
  $("methodology").innerHTML = (data.methodology || []).map((text) => `<li>${esc(text)}</li>`).join("");
  const source = data.session.source || "Saved telemetry dataset", url = data.session.source_url;
  $("source-note").innerHTML = `<strong>Source:</strong> ${esc(source)}${url && /^https?:\/\//i.test(url) ? ` · <a href="${esc(url)}" target="_blank" rel="noopener noreferrer">View original source ↗</a>` : ""}. Driver colours identify the two selected laps within this dashboard.`;
}
async function renderTrack(data) {
  const track = data.track;
  if (!track || !track.x?.length || !track.y?.length) { Plotly.purge("track-chart"); $("track-chart").innerHTML = '<div class="no-track">Position data is unavailable for these laps.</div>'; $("track-caption").textContent = "Speed and driver-input comparisons remain available."; return; }
  $("track-chart").innerHTML = "";
  const traces = [{x:track.x,y:track.y,type:"scatter",mode:"lines",line:{color:"#d8ddcf",width:7},hoverinfo:"skip"}];
  if (track.distance?.length === track.x.length) {
    for (const sector of data.mini_sectors || []) {
      const indexes = track.distance.map((d,i) => d >= sector.start && d <= sector.end ? i : -1).filter((i) => i >= 0);
      if (indexes.length < 2) continue;
      const color = sector.gain >= 0 ? COLORS.a : COLORS.b;
      traces.push({x:indexes.map((i)=>track.x[i]),y:indexes.map((i)=>track.y[i]),type:"scatter",mode:"lines",line:{color,width:4},hoverinfo:"skip"});
    }
    $("track-caption").textContent = "Colour shows local gain · approximate position trace";
  } else $("track-caption").textContent = "Telemetry position trace · approximate geometry";
  traces.push({x:[track.x[0]],y:[track.y[0]],type:"scatter",mode:"markers",marker:{color:"#202722",size:7,line:{color:"#fffefa",width:2}},hoverinfo:"skip"});
  await Plotly.newPlot("track-chart",traces,{height:$("track-chart").clientHeight||222,margin:{l:15,r:15,t:10,b:10},paper_bgcolor:"rgba(0,0,0,0)",plot_bgcolor:"rgba(0,0,0,0)",showlegend:false,xaxis:{visible:false,fixedrange:true},yaxis:{visible:false,scaleanchor:"x",scaleratio:1,fixedrange:true}},chartConfig);
}
async function importSession(event) {
  event.preventDefault(); const button=$("import-button"); button.disabled=true; $("import-status").textContent="Starting FastF1 download…";
  try {
    const result = await api("/api/import",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({year:Number($("import-year").value),event:$("import-event").value.trim()})});
    let sessionId = result.session_id;
    if (!sessionId) {
      if (!result.job_id) throw new Error("The server did not provide an import job.");
      for (;;) {
        await new Promise((resolve)=>setTimeout(resolve,1800));
        const job=await api(`/api/jobs/${encodeURIComponent(result.job_id)}`);
        if (job.status==="error") throw new Error(job.error || "FastF1 could not load this session.");
        if (job.status==="complete") { sessionId=job.session_id; break; }
        $("import-status").textContent=job.message || "Downloading and preparing qualifying telemetry…";
      }
    }
    await loadCatalog(sessionId); await compare(); $("import-status").textContent="Session ready. Your comparison is displayed below.";
  } catch(error) { $("import-status").textContent=errorMessage(error); }
  finally { button.disabled=false; }
}
$("compare-button").addEventListener("click",compare);
$("session-select").addEventListener("change",()=>{populateDrivers();compare();});
$("swap-button").addEventListener("click",()=>{const a=$("driver-a-select").value;$("driver-a-select").value=$("driver-b-select").value;$("driver-b-select").value=a;compare();});
$("export-button").addEventListener("click",()=>{if (!state.comparison) return; const data=state.comparison; location.href=`/api/export?${new URLSearchParams({session:data.session.id,driver_a:data.drivers.a.code,driver_b:data.drivers.b.code})}`;});
$("reset-zoom").addEventListener("click",async()=>{state.syncing=true;try{await Promise.all(chartIds.map((id)=>Plotly.relayout(id,{"xaxis.autorange":true})));}finally{state.syncing=false;}});
$("mini-sectors").addEventListener("click",async(event)=>{const button=event.target.closest("button[data-start]");if(!button)return;state.syncing=true;try{await Promise.all(chartIds.map((id)=>Plotly.relayout(id,{"xaxis.range":[Number(button.dataset.start),Number(button.dataset.end)]})));}finally{state.syncing=false;}});
$("import-form")?.addEventListener("submit",importSession);
(async()=>{try{if(!window.Plotly)throw new Error("The local Plotly chart library is missing. Run the project setup script in VS Code.");await loadCatalog();await compare();}catch(error){showError(errorMessage(error));$("loading-state").hidden=true;$("data-status").textContent="Workspace needs attention";}})();


