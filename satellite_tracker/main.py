from __future__ import annotations

import logging
import asyncio
import os
import sys
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from satellite_tracker.api import iss_service, router
else:
    from .api import iss_service, router


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def allowed_origins() -> list[str]:
    configured = os.getenv("SATELLITE_TRACKER_ALLOWED_ORIGINS")
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]

    return [
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8001",
        "http://localhost:8000",
        "http://localhost:8001",
    ]


async def poll_iss_positions() -> None:
    while True:
        try:
            await asyncio.to_thread(iss_service.refresh_if_due)
        except Exception:
            logger.warning("ISS background refresh failed", exc_info=True)
        await asyncio.sleep(iss_service.poll_interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    iss_poll_task = asyncio.create_task(poll_iss_positions())
    try:
        yield
    finally:
        iss_poll_task.cancel()
        with suppress(asyncio.CancelledError):
            await iss_poll_task

app = FastAPI(
    title="satellite_tracker",
    description="Real-time ISS tracking and satellite orbit prediction API.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def frontend() -> HTMLResponse:
    return HTMLResponse(_FRONTEND_HTML)


_FRONTEND_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>satellite_tracker</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIINfQjT3nIegAeuLt+Y9rrg7FQgH5A9iQw="
        crossorigin="">
  <style>
    .leaflet-pane,
    .leaflet-tile,
    .leaflet-marker-icon,
    .leaflet-marker-shadow,
    .leaflet-tile-container,
    .leaflet-pane > svg,
    .leaflet-pane > canvas,
    .leaflet-zoom-box,
    .leaflet-image-layer,
    .leaflet-layer {
      position: absolute;
      left: 0;
      top: 0;
    }

    .leaflet-container {
      overflow: hidden;
      background: #9fcad4;
      outline-offset: 1px;
      -webkit-tap-highlight-color: transparent;
    }

    .leaflet-container img {
      max-width: none;
      max-height: none;
    }

    .leaflet-map-pane {
      z-index: 400;
    }

    .leaflet-tile-pane {
      z-index: 200;
    }

    .leaflet-overlay-pane {
      z-index: 400;
    }

    .leaflet-shadow-pane {
      z-index: 500;
    }

    .leaflet-marker-pane {
      z-index: 600;
    }

    .leaflet-tooltip-pane {
      z-index: 650;
    }

    .leaflet-popup-pane {
      z-index: 700;
    }

    .leaflet-tile-container {
      pointer-events: none;
    }

    .leaflet-tile,
    .leaflet-marker-icon,
    .leaflet-marker-shadow {
      user-select: none;
      -webkit-user-drag: none;
    }

    .leaflet-tile {
      filter: saturate(0.95) contrast(0.98);
      visibility: hidden;
    }

    .leaflet-tile-loaded {
      visibility: inherit;
    }

    .leaflet-zoom-animated {
      transform-origin: 0 0;
    }

    .leaflet-pane > svg,
    .leaflet-pane > canvas {
      pointer-events: none;
    }

    .leaflet-pane > svg path,
    .leaflet-interactive {
      pointer-events: visiblePainted;
      pointer-events: auto;
    }

    .leaflet-interactive {
      cursor: pointer;
    }

    .leaflet-control {
      position: relative;
      z-index: 800;
      pointer-events: visiblePainted;
      pointer-events: auto;
    }

    .leaflet-top,
    .leaflet-bottom {
      position: absolute;
      z-index: 1000;
      pointer-events: none;
    }

    .leaflet-top {
      top: 0;
    }

    .leaflet-right {
      right: 0;
    }

    .leaflet-bottom {
      bottom: 0;
    }

    .leaflet-left {
      left: 0;
    }

    .leaflet-control-zoom {
      display: none;
    }

    .leaflet-control-attribution {
      margin: 0;
      padding: 2px 7px;
      background: rgba(255, 255, 255, 0.75);
      color: #334;
      font-size: 11px;
    }

    :root {
      --panel-bg: rgba(12, 22, 34, 0.88);
      --panel-border: rgba(255, 255, 255, 0.16);
      --text: #f6f8fb;
      --muted: #b7c4d2;
      --accent: #25d0a5;
      --orbit: #ffd166;
      --history: #5db7ff;
      --danger: #ff6b6b;
    }

    * {
      box-sizing: border-box;
    }

    html,
    body {
      height: 100%;
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #101820;
      color: var(--text);
      overflow: hidden;
    }

    #map {
      position: fixed;
      inset: 0;
      height: 100vh;
      width: 100vw;
    }

    .panel {
      position: fixed;
      z-index: 1000;
      left: 18px;
      top: 18px;
      width: min(360px, calc(100vw - 36px));
      padding: 16px;
      border: 1px solid var(--panel-border);
      border-radius: 8px;
      background: var(--panel-bg);
      box-shadow: 0 18px 60px rgba(0, 0, 0, 0.35);
      backdrop-filter: blur(14px);
    }

    .panel h1 {
      margin: 0 0 12px;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0;
    }

    .status {
      display: flex;
      align-items: center;
      gap: 8px;
      min-height: 22px;
      color: var(--muted);
      font-size: 13px;
    }

    .status-dot {
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 16px rgba(37, 208, 165, 0.8);
      flex: 0 0 auto;
    }

    .status.error .status-dot {
      background: var(--danger);
      box-shadow: 0 0 16px rgba(255, 107, 107, 0.8);
    }

    .metrics {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
      margin-top: 14px;
    }

    .metric {
      min-width: 0;
      padding: 10px;
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.06);
    }

    .metric span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    .metric strong {
      display: block;
      overflow-wrap: anywhere;
      margin-top: 4px;
      font-size: 15px;
      font-weight: 700;
    }

    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 14px;
      color: var(--muted);
      font-size: 12px;
    }

    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }

    .line-swatch {
      width: 22px;
      height: 3px;
      border-radius: 999px;
      background: var(--history);
    }

    .line-swatch.orbit {
      background: var(--orbit);
    }

    .iss-marker {
      position: relative;
      width: 34px;
      height: 34px;
    }

    .iss-marker .pulse,
    .iss-marker .core {
      position: absolute;
      left: 50%;
      top: 50%;
      transform: translate(-50%, -50%);
      border-radius: 50%;
    }

    .iss-marker .pulse {
      width: 34px;
      height: 34px;
      border: 2px solid rgba(37, 208, 165, 0.85);
      animation: pulse 1.8s ease-out infinite;
    }

    .iss-marker .core {
      width: 13px;
      height: 13px;
      border: 2px solid #ffffff;
      background: var(--accent);
      box-shadow: 0 0 18px rgba(37, 208, 165, 0.9);
    }

    @keyframes pulse {
      0% {
        opacity: 0.9;
        transform: translate(-50%, -50%) scale(0.55);
      }
      100% {
        opacity: 0;
        transform: translate(-50%, -50%) scale(1.55);
      }
    }

    @media (max-width: 620px) {
      .panel {
        left: 10px;
        right: 10px;
        top: 10px;
        width: auto;
        padding: 13px;
      }

      .metrics {
        grid-template-columns: 1fr;
        gap: 8px;
      }
    }
  </style>
</head>
<body>
  <div id="map"></div>
  <section class="panel" aria-label="ISS telemetry">
    <h1>satellite_tracker</h1>
    <div id="status" class="status">
      <span class="status-dot"></span>
      <span id="status-text">Starting live feed</span>
    </div>
    <div class="metrics">
      <div class="metric">
        <span>Latitude</span>
        <strong id="latitude">--</strong>
      </div>
      <div class="metric">
        <span>Longitude</span>
        <strong id="longitude">--</strong>
      </div>
      <div class="metric">
        <span>Timestamp</span>
        <strong id="timestamp">--</strong>
      </div>
      <div class="metric">
        <span>History</span>
        <strong id="history-count">0 points</strong>
      </div>
    </div>
    <div class="legend" aria-label="Map layers">
      <span class="legend-item"><span class="line-swatch"></span> Recent path</span>
      <span class="legend-item"><span class="line-swatch orbit"></span> Predicted orbit</span>
    </div>
  </section>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
          integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
          crossorigin=""></script>
  <script>
    const map = L.map("map", {
      worldCopyJump: true,
      zoomControl: true
    }).setView([0, 0], 2);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      minZoom: 2,
      maxZoom: 7,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }).addTo(map);

    const issIcon = L.divIcon({
      className: "iss-marker",
      html: '<span class="pulse"></span><span class="core"></span>',
      iconSize: [34, 34],
      iconAnchor: [17, 17]
    });

    let issMarker = null;
    let historyLine = L.polyline([], { color: "#5db7ff", weight: 3, opacity: 0.85 }).addTo(map);
    let orbitLine = L.polyline([], { color: "#ffd166", weight: 2, opacity: 0.95, dashArray: "7 8" }).addTo(map);
    let hasCenteredMap = false;

    const statusEl = document.getElementById("status");
    const statusText = document.getElementById("status-text");
    const latitudeEl = document.getElementById("latitude");
    const longitudeEl = document.getElementById("longitude");
    const timestampEl = document.getElementById("timestamp");
    const historyCountEl = document.getElementById("history-count");

    async function fetchJson(url) {
      const response = await fetch(url, { headers: { "Accept": "application/json" } });
      if (!response.ok) {
        let message = `${response.status} ${response.statusText}`;
        try {
          const payload = await response.json();
          message = payload.detail || message;
        } catch (_) {
          message = response.statusText || message;
        }
        throw new Error(message);
      }
      return response.json();
    }

    function pointFromPosition(position) {
      return [position.latitude, position.longitude];
    }

    function splitAntimeridianPath(points) {
      const segments = [];
      let currentSegment = [];

      for (const point of points) {
        const latLng = pointFromPosition(point);
        const previous = currentSegment[currentSegment.length - 1];

        if (previous && Math.abs(latLng[1] - previous[1]) > 180) {
          if (currentSegment.length > 1) {
            segments.push(currentSegment);
          }
          currentSegment = [];
        }

        currentSegment.push(latLng);
      }

      if (currentSegment.length > 1) {
        segments.push(currentSegment);
      }

      return segments;
    }

    function setStatus(text, isError = false) {
      statusText.textContent = text;
      statusEl.classList.toggle("error", isError);
    }

    function formatCoordinate(value, suffixPositive, suffixNegative) {
      const suffix = value >= 0 ? suffixPositive : suffixNegative;
      return `${Math.abs(value).toFixed(4)} ${suffix}`;
    }

    function updateTelemetry(position, message = "Live ISS position updated", isError = false) {
      const latLng = pointFromPosition(position);
      if (!issMarker) {
        issMarker = L.marker(latLng, { icon: issIcon, title: "ISS" }).addTo(map);
      } else {
        issMarker.setLatLng(latLng);
      }

      if (!hasCenteredMap) {
        map.setView(latLng, 3);
        hasCenteredMap = true;
      }

      latitudeEl.textContent = formatCoordinate(position.latitude, "N", "S");
      longitudeEl.textContent = formatCoordinate(position.longitude, "E", "W");
      timestampEl.textContent = new Date(position.timestamp).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
      });
      setStatus(message, isError);
    }

    async function refreshLive() {
      try {
        const position = await fetchJson("/iss/live");
        updateTelemetry(position);
      } catch (error) {
        try {
          const payload = await fetchJson("/iss/history?limit=1");
          const lastKnown = payload.positions[payload.positions.length - 1];
          if (lastKnown) {
            updateTelemetry(lastKnown, `Live feed unavailable: ${error.message}`, true);
            return;
          }
        } catch (_) {
        }
        setStatus(`Live feed unavailable: ${error.message}`, true);
      }
    }

    async function refreshHistory() {
      try {
        const payload = await fetchJson("/iss/history?limit=160");
        historyLine.setLatLngs(splitAntimeridianPath(payload.positions));
        historyCountEl.textContent = `${payload.count} ${payload.count === 1 ? "point" : "points"}`;
      } catch (error) {
        historyCountEl.textContent = "unavailable";
      }
    }

    async function refreshOrbit() {
      try {
        const payload = await fetchJson("/satellite/orbit?name=ISS%20(ZARYA)&minutes=92&step_seconds=60");
        orbitLine.setLatLngs(splitAntimeridianPath(payload.points));
      } catch (error) {
        console.warn("Orbit refresh failed", error);
      }
    }

    async function refreshAll() {
      await Promise.allSettled([refreshLive(), refreshHistory(), refreshOrbit()]);
    }

    refreshAll();
    setInterval(refreshLive, 5000);
    setInterval(refreshHistory, 15000);
    setInterval(refreshOrbit, 300000);
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("satellite_tracker.main:app", host="0.0.0.0", port=8000, reload=False)
