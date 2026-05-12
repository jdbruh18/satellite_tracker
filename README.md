# satellite_tracker

FastAPI + Leaflet app for **live International Space Station (ISS) tracking**, **position history**, and **satellite orbit prediction** using **TLEs**.

This repo runs a small FastAPI service that:

- Polls the upstream ISS live-position feed and stores recent positions locally (SQLite)
- Exposes API endpoints for live position + recent history
- Fetches and caches TLEs from CelesTrak
- Generates orbit predictions (lat/lon/alt + timestamps)
- Serves a simple Leaflet map UI at `/`

---

## Features

- **Live ISS tracking** (`/iss/live`)
- **Recent position history** (`/iss/history`) persisted in `satellite_tracker/data/positions.sqlite3`
- **Orbit prediction** for ISS (or other satellites present in the TLE source) (`/satellite/orbit`)
- **Health check** (`/health`)
- **Built-in frontend** map (`/`) using Leaflet + OpenStreetMap tiles

---

## Quickstart

### 1) Requirements

- Python 3.10+ (3.11+ recommended)

### 2) Install dependencies

```bash
python -m pip install -r requirements.txt
```

### 3) Run the server

```bash
python -m uvicorn satellite_tracker.main:app --host 127.0.0.1 --port 8001 --reload
```

### 4) Open the map UI

- http://127.0.0.1:8001

### 5) Try the API

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8001/iss/live
curl "http://127.0.0.1:8001/iss/history?limit=25"
curl "http://127.0.0.1:8001/satellite/orbit?name=ISS%20(ZARYA)&minutes=92&step_seconds=60"
```

---

## API Reference

Base URL (local): `http://127.0.0.1:8001`

### `GET /`

Serves the Leaflet frontend.

### `GET /health`

Simple health check.

**Response**

```json
{ "status": "ok", "service": "satellite_tracker", "version": "1.0.0" }
```

### `GET /iss/live`

Returns the latest known ISS position.

- The app runs a background poller that refreshes the stored position periodically.
- If the upstream provider is temporarily unavailable, the service may return the most recent stored position (if one exists).

### `GET /iss/history`

Returns recent stored positions.

**Query params**

- `limit` (int, default `100`, min `1`, max `1000`)

### `GET /satellite/orbit`

Generates an orbit prediction for a satellite based on TLE data.

**Query params**

- `name` (string, default `ISS (ZARYA)`)
- `minutes` (int, default `92`, min `1`, max `1440`)
- `step_seconds` (int, default `60`, min `5`, max `600`)
- `force_refresh` (bool, default `false`) – force refresh of cached TLEs

---

## Configuration

### CORS allowed origins

Set `SATELLITE_TRACKER_ALLOWED_ORIGINS` to a comma-separated list of allowed origins.

Example:

```bash
export SATELLITE_TRACKER_ALLOWED_ORIGINS="http://localhost:3000,http://127.0.0.1:3000"
```

If not set, the app allows common localhost dev origins (see `satellite_tracker/main.py`).

---

## Data & Caching

- Position history is stored in SQLite: `satellite_tracker/data/positions.sqlite3`
- TLEs are cached to: `satellite_tracker/data/tle_cache.json`

The app uses a simple inter-process file lock when refreshing to avoid multiple workers refreshing at the same time.

---

## Development Notes

### Swagger / OpenAPI

Once running, FastAPI docs are available at:

- Swagger UI: http://127.0.0.1:8001/docs
- ReDoc: http://127.0.0.1:8001/redoc

### Running without `uvicorn`

You can also run via any ASGI server that can load `satellite_tracker.main:app`.

---

## Upstream Data Sources

- ISS live position: Open Notify (`http://api.open-notify.org/iss-now.json`)
- TLEs: CelesTrak stations feed (`https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle`)

---

## License

Add a license file if you plan to distribute this project (MIT/Apache-2.0 are common choices).