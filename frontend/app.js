/* TrafficFlowDB dashboard — vanilla JS, no build step.
   Live data via WebSocket (/ws/live) with HTTP polling fallback every 2s. */
"use strict";

const API = ""; // same origin (backend serves this page)
const POLL_MS = 2000;
const COLORS = { LOW: "#30d158", MEDIUM: "#ffd60a", HIGH: "#ff453a" };

const map = L.map("map", { zoomControl: true }).setView([11.03, 76.98], 12);
L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap &copy; CARTO",
}).addTo(map);

const segLines = new Map();   // segment_id -> L.polyline
const nodeMarkers = new Map();
let vehicleLayer = L.layerGroup().addTo(map);
let routeLayer = L.layerGroup().addTo(map);
let segments = [];
let lastRouteSegs = [];

const $ = (id) => document.getElementById(id);

async function getJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(path + " -> " + r.status);
  return r.json();
}

function setStatus(online, text) {
  $("statusDot").classList.toggle("on", online);
  $("livePill").textContent = text;
}

/* ---- static network -------------------------------------------------- */
async function loadNetwork() {
  const [nodes, segs] = await Promise.all([
    getJSON("/api/network/intersections"),
    getJSON("/api/network/segments"),
  ]);
  segments = segs;

  const src = $("srcSel"), dst = $("dstSel");
  src.innerHTML = dst.innerHTML = nodes
    .map((n) => `<option value="${n.id}">${n.name}</option>`).join("");
  src.value = 1;
  dst.value = nodes.length > 5 ? 6 : nodes[nodes.length - 1].id;

  for (const n of nodes) {
    if (nodeMarkers.has(n.id)) continue;
    const m = L.circleMarker([n.lat, n.lon], {
      radius: 4, color: "#0071e3", weight: 2, fillColor: "#fff", fillOpacity: 1,
    }).bindTooltip(n.name).addTo(map);
    nodeMarkers.set(n.id, m);
  }
  for (const s of segs) {
    if (segLines.has(s.id)) continue;
    const line = L.polyline([[s.a_lat, s.a_lon], [s.b_lat, s.b_lon]], {
      color: COLORS.LOW, weight: 5, opacity: 0.85, lineCap: "round",
    }).bindTooltip(`${s.name}<br>${s.distance_km} km · limit ${s.speed_limit} km/h`)
      .addTo(map);
    segLines.set(s.id, line);
  }
}

/* ---- live rendering --------------------------------------------------- */
function renderTraffic(rows) {
  let high = 0, med = 0;
  for (const t of rows) {
    const line = segLines.get(t.segment_id);
    if (line) {
      line.setStyle({ color: COLORS[t.congestion_level] || COLORS.LOW });
      line.setTooltipContent(
        `<b>${t.segment_name}</b><br>${t.average_speed.toFixed(0)} km/h · ` +
        `${t.vehicle_count} vehicles · ${t.congestion_level}`);
    }
    if (t.congestion_level === "HIGH") high++;
    else if (t.congestion_level === "MEDIUM") med++;
  }
  // Re-draw the active route on top so it never sinks under traffic colors.
  if (lastRouteSegs.length) drawRoute(lastRouteSegs);
  return { high, med };
}

function renderPositions(rows) {
  vehicleLayer.clearLayers();
  for (const p of rows.slice(0, 400)) {
    L.circleMarker([p.latitude, p.longitude], {
      radius: 4, color: "#1d1d1f", weight: 1.5,
      fillColor: p.vehicle_type === "emergency" ? "#ff453a" : "#0071e3",
      fillOpacity: 0.95,
    }).bindTooltip(`${p.vehicle_number} · ${Math.round(p.speed_kmh)} km/h`)
      .addTo(vehicleLayer);
  }
}

function renderStats(s, cong) {
  $("hsVehicles").textContent = s.active_vehicles;
  $("hsFixes").textContent = s.gps_updates_last_5min;
  $("hsCongested").textContent = cong.high + cong.med;
  $("hsQuery").textContent = s.query_ms + " ms";
}

function renderTable(rows) {
  $("netBody").innerHTML = rows.map((t) => `
    <tr>
      <td>${t.segment_name}</td>
      <td>${t.distance_km}</td>
      <td>${Number(t.average_speed).toFixed(0)}</td>
      <td>${t.vehicle_count}</td>
      <td>${Number(t.density).toFixed(2)}</td>
      <td><span class="pill ${t.congestion_level}">${t.congestion_level}</span></td>
    </tr>`).join("");
}

async function pollOnce() {
  try {
    const [traffic, positions, stats] = await Promise.all([
      getJSON("/api/traffic/summary"),
      getJSON("/api/network/positions"),
      getJSON("/api/stats"),
    ]);
    const cong = renderTraffic(traffic);
    renderPositions(positions);
    renderStats(stats, cong);
    renderTable(traffic);
    setStatus(true, `live · ${positions.length} vehicles · ${new Date().toLocaleTimeString()}`);
  } catch (e) {
    setStatus(false, "reconnecting…");
  }
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
      getJSON("/api/stats").then((s) => {
        renderStats(s, cong);
        renderTable(msg.traffic || []);
      }).catch(() => {});
      setStatus(true, `live · ${(msg.positions || []).length} vehicles · ${new Date().toLocaleTimeString()}`);
    } catch { /* ignore malformed frames */ }
  };
  ws.onclose = () => setTimeout(connectWS, 3000);
  ws.onerror = () => ws.close();
}

/* ---- routing ----------------------------------------------------------- */
function drawRoute(segIds) {
  routeLayer.clearLayers();
  for (const id of segIds) {
    const s = segments.find((x) => x.id === id);
    if (!s) continue;
    L.polyline([[s.a_lat, s.a_lon], [s.b_lat, s.b_lon]], {
      color: "#0071e3", weight: 8, opacity: 0.9, lineCap: "round",
    }).addTo(routeLayer);
  }
}

$("routeBtn").addEventListener("click", async () => {
  const btn = $("routeBtn");
  btn.disabled = true;
  btn.textContent = "Routing…";
  try {
    const body = {
      source_id: Number($("srcSel").value),
      destination_id: Number($("dstSel").value),
      priority: $("prioBox").checked,
    };
    const r = await (await fetch(API + "/api/routes/request", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })).json();
    if (!r.route_id) throw new Error(r.detail || "no route");
    lastRouteSegs = r.segment_path;
    drawRoute(r.segment_path);
    const box = $("routeOut");
    box.hidden = false;
    box.innerHTML = `
      <div class="route-meta">
        <div><strong>${r.estimated_time_min} min</strong><span>estimated travel time</span></div>
        <div><strong>${r.total_distance_km} km</strong><span>total distance</span></div>
        <div><strong>${r.traffic_score}×</strong><span>traffic penalty</span></div>
        <div><strong>${r.source} → ${r.destination}</strong><span>recommended route</span></div>
      </div>
      <ol class="legs">
        ${r.legs.map((l, i) => `
          <li><span class="pill ${l.congestion}">${l.congestion}</span>
          <span><b>${i + 1}.</b> ${l.segment_name} — ${l.distance_km} km, ~${l.estimated_min} min</span></li>`).join("")}
      </ol>`;
    box.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    alert("Routing failed: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Find best route";
  }
});

/* ---- boot --------------------------------------------------------------- */
(async function boot() {
  setStatus(false, "connecting…");
  try {
    await loadNetwork();
  } catch (e) {
    setStatus(false, "API unreachable — start the backend first");
    return;
  }
  await pollOnce();
  setInterval(pollOnce, POLL_MS); // fallback + table/stats refresh
  connectWS();                    // instant map updates when available
})();
