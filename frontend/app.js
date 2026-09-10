/* TrafficFlowDB v2 dashboard — vanilla JS, no build step.
   WS (/ws/live) streams traffic + positions + query log; HTTP polling backs it up. */
"use strict";

const API = "";
const COLORS = { LOW: "#30d158", MEDIUM: "#ffd60a", HIGH: "#ff453a" };
const VEH_COLORS = { car: "#0071e3", bus: "#ff9f0a", emergency: "#ff453a" };
const INDIA_VIEW = { c: [22.8, 79.5], z: 5 };

const $ = (id) => document.getElementById(id);
let POLL_MS = 2000;

/* ---- theme -------------------------------------------------------------- */
function setTheme(t, animate = true) {
  const apply = () => document.documentElement.dataset.theme = t;
  try { localStorage.setItem("tfdb-theme", t); } catch { /* private mode */ }
  if (animate && document.startViewTransition) {
    const w = $("wipe");
    document.startViewTransition(apply);
    w.classList.remove("go"); void w.offsetWidth; w.classList.add("go");
  } else apply();
}
(function initTheme() {
  let t = "light";
  try { t = localStorage.getItem("tfdb-theme") || "light"; } catch { /* ignore */ }
  const qp = new URLSearchParams(location.search).get("theme");
  if (qp === "light" || qp === "dark") t = qp; // ?theme=dark deep-link
  document.documentElement.dataset.theme = t;
})();
$("themeBtn").addEventListener("click", (e) => {
  const r = e.currentTarget.getBoundingClientRect();
  const w = $("wipe");
  w.style.setProperty("--wx", (r.left + r.width / 2) + "px");
  w.style.setProperty("--wy", (r.top + r.height / 2) + "px");
  setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
});

/* ---- map ----------------------------------------------------------------- */
const map = L.map("map", { zoomControl: true, worldCopyJump: true })
  .setView(INDIA_VIEW.c, INDIA_VIEW.z);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19, attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const segLines = new Map();
const nodeMarkers = new Map();
const vehicleLayer = L.layerGroup().addTo(map);
const routeLayer = L.layerGroup().addTo(map);
let segments = [], nodes = [], lastRouteSegs = [], lastTraffic = [];

/* ---- helpers -------------------------------------------------------------- */
async function getJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(path + " -> " + r.status);
  return r.json();
}
async function postJSON(path, body) {
  const r = await fetch(API + path, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || r.status);
  return data;
}
async function putJSON(path, body) {
  const r = await fetch(API + path, {
    method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}
function setStatus(online, text) {
  $("statusDot").classList.toggle("on", online);
  $("livePill").textContent = text;
}
let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), 2600);
}
function tweenNum(el, to, suffix = "") {
  const from = parseFloat(el.dataset.v || "0");
  el.dataset.v = to;
  const t0 = performance.now();
  (function step(t) {
    const k = Math.max(0, Math.min((t - t0) / 600, 1));
    const v = from + (to - from) * (1 - Math.pow(1 - k, 3));
    el.textContent = (Number.isInteger(to) ? Math.round(v) : v.toFixed(2)) + suffix;
    if (k < 1) requestAnimationFrame(step);
  })(t0);
}

/* ---- network --------------------------------------------------------------- */
function optGroups(list) {
  const nat = list.filter((n) => n.scope === "national");
  const met = list.filter((n) => n.scope !== "national");
  const g = (t, arr) => arr.length
    ? `<optgroup label="${t}">${arr.map((n) => `<option value="${n.id}">${n.name}</option>`).join("")}</optgroup>` : "";
  return g("National hubs", nat) + g("Other places", met);
}
async function loadNetwork() {
  [nodes, segments] = await Promise.all([
    getJSON("/api/network/intersections"),
    getJSON("/api/network/segments"),
  ]);
  const src = $("srcSel"), dst = $("dstSel");
  src.innerHTML = optGroups(nodes); dst.innerHTML = optGroups(nodes);
  src.value = 101; dst.value = 124; // Delhi -> Mumbai showcase
  $("jamSel").innerHTML = segments
    .map((s) => `<option value="${s.id}">#${s.id} ${s.name}</option>`).join("");
  $("jamSel").value = 45;
  $("netSub").textContent =
    `${nodes.length} intersections · ${segments.length} segments · one row per segment, updated on every GPS fix.`;
  for (const n of nodes) {
    if (nodeMarkers.has(n.id)) continue;
    nodeMarkers.set(n.id, L.circleMarker([n.lat, n.lon], {
      radius: n.scope === "national" ? 5 : 3.5, color: "#0071e3", weight: 2,
      fillColor: "#fff", fillOpacity: 1,
    }).bindTooltip(n.name).addTo(map));
  }
  for (const s of segments) {
    if (segLines.has(s.id)) continue;
    segLines.set(s.id, L.polyline([[s.a_lat, s.a_lon], [s.b_lat, s.b_lon]], {
      color: COLORS.LOW, weight: s.scope === "trunk" ? 4 : 5,
      opacity: 0.85, lineCap: "round",
    }).bindTooltip(`${s.name}<br>${s.distance_km} km · limit ${s.speed_limit} km/h`).addTo(map));
  }
}

/* ---- live rendering ---------------------------------------------------------- */
function renderTraffic(rows) {
  lastTraffic = rows;
  let high = 0, med = 0;
  for (const t of rows) {
    const line = segLines.get(t.segment_id);
    if (line) {
      line.setStyle({ color: COLORS[t.congestion_level] || COLORS.LOW });
      line.setTooltipContent(
        `<b>${t.segment_name}</b><br>${Number(t.average_speed).toFixed(0)} km/h · ` +
        `${t.vehicle_count} vehicles · ${t.congestion_level}`);
    }
    if (t.congestion_level === "HIGH") high++;
    else if (t.congestion_level === "MEDIUM") med++;
  }
  if (lastRouteSegs.length) drawRoute(lastRouteSegs, false);
  renderTable();
  return { high, med };
}
function renderPositions(rows) {
  vehicleLayer.clearLayers();
  for (const p of rows.slice(0, 400)) {
    L.circleMarker([p.latitude, p.longitude], {
      radius: 3.5, color: "#1d1d1f", weight: 1.5,
      fillColor: VEH_COLORS[p.vehicle_type] || VEH_COLORS.car,
      fillOpacity: 0.95,
    }).bindTooltip(`${p.vehicle_number} · ${p.vehicle_type} · ${Math.round(p.speed_kmh)} km/h`).addTo(vehicleLayer);
  }
}
function renderStats(s, cong) {
  tweenNum($("hsVehicles"), s.active_vehicles);
  tweenNum($("hsFixes"), s.gps_updates_last_5min);
  tweenNum($("hsCongested"), cong.high + cong.med);
  tweenNum($("hsRoutes"), s.routes_computed);
  $("hsQuery").textContent = s.query_ms + " ms";
}
function renderTable() {
  $("netBody").innerHTML = lastTraffic.map((t) => `
    <tr><td>${t.segment_name}</td>
    <td><span class="scope-tag ${t.scope}">${t.scope}</span></td>
    <td>${t.distance_km}</td><td>${Number(t.average_speed).toFixed(0)}</td>
    <td>${t.vehicle_count}</td><td>${Number(t.density).toFixed(2)}</td>
    <td><span class="pill ${t.congestion_level}">${t.congestion_level}</span></td></tr>`).join("");
}
/* ---- boot + live loops ----------------------------------------------------------------------- */

async function pollOnce() {
  try {
    const [traffic, positions, stats] = await Promise.all([
      getJSON("/api/traffic/summary"), getJSON("/api/network/positions"), getJSON("/api/stats"),
    ]);
    const cong = renderTraffic(traffic);
    renderPositions(positions);
    renderStats(stats, cong);
    setStatus(true, `live · ${positions.length} vehicles · ${new Date().toLocaleTimeString()}`);
  } catch { setStatus(false, "reconnecting…"); }
}
function connectWS() {
  let ws;
  try {
    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/live");
  } catch { return; }
  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      const cong = renderTraffic(msg.traffic || []);
      renderPositions(msg.positions || []);
      appendLogs(msg.logs || []);
      getJSON("/api/stats").then((s) => renderStats(s, cong)).catch(() => {});
      setStatus(true, `live · ${(msg.positions || []).length} vehicles · ${new Date().toLocaleTimeString()}`);
    } catch { /* ignore malformed frames */ }
  };
  ws.onclose = () => setTimeout(connectWS, 3000);
  ws.onerror = () => ws.close();
}

/* ---- live query log ------------------------------------------------------------ */
const seenLogIds = new Set();
let logPaused = false, logFilter = "ALL", logTotal = 0, logSqlMs = 0, logSqlN = 0;
function appendLogs(entries) {
  const term = $("terminal");
  let added = false;
  for (const e of entries) {
    if (seenLogIds.has(e.id)) continue;
    seenLogIds.add(e.id);
    logTotal++;
    if (e.cat === "SQL") { logSqlMs += e.ms; logSqlN++; }
    if (e.cat === "ROUTE") $("lgRoute").textContent = e.ms + " ms";
    if (logPaused || (logFilter !== "ALL" && e.cat !== logFilter)) continue;
    const div = document.createElement("div");
    div.className = "log-line " + e.cat;
    div.innerHTML = `<span class="lt">+${e.t}s</span> <span class="lid">#${e.id}</span> ` +
      `<b>${e.cat}</b> ${escapeHtml(e.sql)} <span class="ms">${e.ms} ms</span>` +
      (e.detail ? ` <span class="det">— ${escapeHtml(e.detail)}</span>` : "");
    term.appendChild(div);
    while (term.children.length > 150) term.removeChild(term.firstChild);
    added = true;
  }
  if (added) term.scrollTop = term.scrollHeight;
  $("lgCount").textContent = logTotal;
  $("lgAvg").textContent = (logSqlN ? (logSqlMs / logSqlN).toFixed(1) : "0") + " ms";
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
}
document.querySelectorAll("#logFilters button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll("#logFilters button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); logFilter = b.dataset.f;
  }));
$("logPause").addEventListener("click", () => {
  logPaused = !logPaused;
  $("logPause").textContent = logPaused ? "Resume" : "Pause";
});
$("logClear").addEventListener("click", () => { $("terminal").innerHTML = ""; });

/* ---- routing --------------------------------------------------------------------- */
function drawRoute(segIds, fly = true) {
  routeLayer.clearLayers();
  const bounds = [];
  for (const id of segIds) {
    const s = segments.find((x) => x.id === id);
    if (!s) continue;
    bounds.push([s.a_lat, s.a_lon], [s.b_lat, s.b_lon]);
    L.polyline([[s.a_lat, s.a_lon], [s.b_lat, s.b_lon]], {
      color: "#0071e3", weight: 7, opacity: 0.95, lineCap: "round", className: "route-anim",
    }).addTo(routeLayer);
  }
  if (fly && bounds.length) map.flyToBounds(bounds, { padding: [60, 60], duration: 1.2 });
}
function routeHTML(r) {
  const c = r.comparison;
  let cmp = "";
  if (c) {
    cmp = c.same_route
      ? `<p class="verdict">The fastest route <b>is</b> the shortest one right now — nothing to beat.</p>`
      : `<div class="versus">
          <div class="vs-card"><span>Shortest</span><strong>${c.shortest.total_distance_km} km</strong><em>${c.shortest.estimated_time_min} min</em></div>
          <div class="vs-mid">vs</div>
          <div class="vs-card fast"><span>Fastest ★</span><strong>${r.total_distance_km} km</strong><em>${r.estimated_time_min} min</em></div>
        </div>
        <p class="verdict">Fastest saves <b>${c.saved_min} min</b> for <b>+${c.extra_km} km</b> extra road.</p>`;
  }
  return `
    <div class="route-meta">
      <div><strong>${r.estimated_time_min} min</strong><span>estimated travel time</span></div>
      <div><strong>${r.total_distance_km} km</strong><span>total distance</span></div>
      <div><strong>${r.traffic_score}×</strong><span>traffic penalty</span></div>
      <div><strong>${escapeHtml(r.source)} → ${escapeHtml(r.destination)}</strong><span>recommended route</span></div>
    </div>
    ${cmp}
    <ol class="legs">
      ${r.legs.map((l, i) => `<li><span class="pill ${l.congestion}">${l.congestion}</span>
        <span><b>${i + 1}.</b> ${escapeHtml(l.segment_name)} — ${l.distance_km} km, ~${l.estimated_min} min</span></li>`).join("")}
    </ol>`;
}
$("routeBtn").addEventListener("click", async () => {
  const btn = $("routeBtn");
  btn.disabled = true; btn.textContent = "Routing…";
  try {
    const r = await postJSON("/api/routes/request", {
      source_id: Number($("srcSel").value), destination_id: Number($("dstSel").value),
      priority: $("prioBox").checked,
    });
    lastRouteSegs = r.segment_path; drawRoute(r.segment_path);
    const box = $("routeOut");
    box.hidden = false; box.innerHTML = routeHTML(r);
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) { toast("Routing failed: " + e.message); }
  finally { btn.disabled = false; btn.textContent = "Find best route"; }
});

/* ---- SQL Lab ------------------------------------------------------------------------ */
async function runSql(text) {
  const q = (text !== undefined ? text : $("sqlInput").value).trim();
  if (!q) return;
  const box = $("sqlOut");
  box.hidden = false; box.innerHTML = "<p>Running as read-only role…</p>";
  try {
    const r = await postJSON("/api/sql/run", { sql: q });
    const head = r.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
    const body = r.rows.map((row) =>
      `<tr>${row.map((v) => `<td>${escapeHtml(v === null ? "NULL" : String(v))}</td>`).join("")}</tr>`).join("");
    box.innerHTML = `
      <div class="sql-meta"><b>${r.rowcount}</b> rows in ${r.ms} ms${r.truncated ? " (first 200 shown)" : ""}</div>
      <div class="sql-scroll table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body || '<tr><td>No rows.</td></tr>'}</tbody></table></div>`;
  } catch (e) { box.innerHTML = `<p class="cmd-error">Blocked: ${escapeHtml(e.message)}</p>`; }
}
async function loadSqlLab() {
  try {
    const { tables } = await getJSON("/api/sql/schema");
    $("schemaCount").textContent = `${tables.length} tables & views`;
    $("schemaGrid").innerHTML = tables.map((t) => `
      <div class="schema-table"><b>${escapeHtml(t.name)}</b>
      ${t.columns.map((c) => `<span><i>${escapeHtml(c.name)}</i> · ${escapeHtml(c.type)}</span>`).join("")}</div>`).join("");
  } catch { $("schemaCount").textContent = "unavailable (backend starting?)"; }
  try {
    const { samples } = await getJSON("/api/sql/samples");
    $("sqlChips").innerHTML = samples.map((s) =>
      `<button class="chip" data-sql="${escapeHtml(s.sql)}">${escapeHtml(s.title)}</button>`).join("");
    document.querySelectorAll("#sqlChips .chip").forEach((c) =>
      c.addEventListener("click", () => { $("sqlInput").value = c.dataset.sql; runSql(c.dataset.sql); }));
  } catch { /* samples are a nicety */ }
}
/* ---- fleet (drawer) ---------------------------------------------------------------------- */
$("fleetRange").addEventListener("input", () => ($("fleetVal").textContent = $("fleetRange").value));
async function loadFleet() {
  try {
    const f = await getJSON("/api/fleet");
    $("fleetOn").checked = f.enabled;
    $("fleetRange").value = f.target;
    $("fleetVal").textContent = f.target;
    $("fleetLive").textContent = f.enabled ? `${f.alive} live` : "";
    $("fleetNote").textContent = f.enabled
      ? `Running: ${f.alive} vehicles live${f.last.ingested ? `, last tick ${f.last.ingested} fixes in ${f.last.ms} ms` : ""}.`
      : "Spawns/retires live to the target — OD trips through the bulk ingest path. No terminal process needed.";
  } catch { /* fleet endpoint missing on old backend */ }
}
$("fleetApply").addEventListener("click", async () => {
  try {
    const f = await postJSON("/api/fleet", {
      enabled: $("fleetOn").checked, count: Number($("fleetRange").value),
    });
    $("fleetLive").textContent = f.enabled ? `${f.alive} live` : "";
    $("fleetNote").textContent = f.enabled
      ? `Running — spawning toward ${f.target} vehicles.`
      : "Fleet stopped and retired.";
    toast(f.enabled ? `Fleet → ${f.target} vehicles` : "Fleet stopped");
    pollOnce(); // site-wide counts refresh immediately, not next tick
  } catch (e) { toast("Fleet failed: " + e.message); }
});
/* (NL console rendering retired in favor of SQL Lab — /api/command stays available.) */
/* (option-chip wiring retired with the NL console.) */
$("sqlRun").addEventListener("click", () => runSql());
$("sqlInput").addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runSql();
});
document.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    $("sqllab").scrollIntoView({ behavior: "smooth" });
    setTimeout(() => $("sqlInput").focus(), 350);
  }
});

/* ---- customize drawer ------------------------------------------------------------------ */
function openDrawer(o) {
  $("drawer").classList.toggle("closed", !o);
  $("scrim").hidden = !o;
}
$("customBtn").addEventListener("click", () => openDrawer(true));
$("drawerClose").addEventListener("click", () => openDrawer(false));
$("scrim").addEventListener("click", () => openDrawer(false));
document.addEventListener("keydown", (e) => { if (e.key === "Escape") openDrawer(false); });
$("drawer").classList.add("closed");

$("winRange").addEventListener("input", () => ($("winVal").textContent = $("winRange").value + " min"));
$("pollRange").addEventListener("input", () => ($("pollVal").textContent = Number($("pollRange").value).toFixed(1) + " s"));

async function loadConfig() {
  try {
    const c = await getJSON("/api/config");
    $("winRange").value = c.traffic_window_minutes;
    $("winVal").textContent = c.traffic_window_minutes + " min";
    $("pollRange").value = c.poll_seconds;
    $("pollVal").textContent = Number(c.poll_seconds).toFixed(1) + " s";
    POLL_MS = c.poll_seconds * 1000;
    $("thHs").value = c.thresholds.high_speed;
    $("thHd").value = c.thresholds.high_density;
    $("thMs").value = c.thresholds.med_speed;
    $("thMd").value = c.thresholds.med_density;
  } catch { /* backend with old config: controls keep defaults */ }
}
$("cfgApply").addEventListener("click", async () => {
  try {
    const c = await putJSON("/api/config", {
      traffic_window_minutes: Number($("winRange").value),
      poll_seconds: Number($("pollRange").value),
      thresholds: {
        high_speed: Number($("thHs").value), high_density: Number($("thHd").value),
        med_speed: Number($("thMs").value), med_density: Number($("thMd").value),
      },
    });
    POLL_MS = c.poll_seconds * 1000;
    $("cfgNote").textContent = `Applied — window ${c.traffic_window_minutes} min, thresholds rewritten, all segments recomputed.`;
    toast("Configuration applied live");
    pollOnce();
  } catch (e) { toast("Apply failed: " + e.message); }
});
$("jamFire").addEventListener("click", async () => {
  try {
    const r = await postJSON("/api/scenarios/jam", {
      segment_id: Number($("jamSel").value), count: Number($("jamCount").value),
    });
    toast(`Jam on ${r.segment} → ${r.traffic.congestion}`);
    pollOnce();
  } catch (e) { toast("Jam failed: " + e.message); }
});
$("rushFire").addEventListener("click", async () => {
  try {
    const r = await postJSON("/api/scenarios/rush-hour", {});
    toast(`Rush hour: ${r.injected} vehicles on ${r.segments} corridors`);
    pollOnce();
  } catch (e) { toast("Failed: " + e.message); }
});
$("resetFire").addEventListener("click", async () => {
  try {
    const r = await postJSON("/api/scenarios/reset", {});
    toast(`Cleared ${r.removed_scenario_vehicles} scenario vehicles`);
    pollOnce();
  } catch (e) { toast("Failed: " + e.message); }
});

/* ---- reveal on scroll ----------------------------------------------------------------------- */
const io = new IntersectionObserver((es) =>
  es.forEach((e) => e.isIntersecting && e.target.classList.add("in")), { threshold: 0.08 });
document.querySelectorAll(".reveal").forEach((el) => io.observe(el));

/* ---- boot ---------------------------------------------------------------------------------------- */
(async function boot() {
  setStatus(false, "connecting…");
  try {
    await loadConfig();
    await loadNetwork();
    await loadSqlLab();
    await loadFleet();
    try {
      const { logs } = await getJSON("/api/logs?limit=25");
      appendLogs(logs);
    } catch { /* logs catch up over WS */ }
  } catch {
    setStatus(false, "API unreachable — start the backend first");
    return;
  }
  await pollOnce();
  (function schedulePoll() { // re-reads POLL_MS every cycle: refresh slider takes effect live
    setTimeout(async () => { await pollOnce(); schedulePoll(); }, POLL_MS);
  })();
  setInterval(async () => { // keep poll cadence + logs fresh even if WS drops
    try { appendLogs((await getJSON("/api/logs?limit=25")).logs); } catch { /* ignore */ }
  }, 5000);
  connectWS();
  if (new URLSearchParams(location.search).get("drawer") === "1") openDrawer(true);
})();
