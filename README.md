# satellite_tracker

FastAPI backend for live ISS tracking, TLE fetching from CelesTrak, Skyfield orbit prediction, recent position history, and a Leaflet map frontend.

## Run

From this project root:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn satellite_tracker.main:app --host 127.0.0.1 --port 8001 --reload
```

Open the map:

```text
http://127.0.0.1:8001
```

## API

```text
GET /iss/live
GET /iss/history
GET /satellite/orbit
GET /health
```

Example:

```powershell
Invoke-RestMethod "http://127.0.0.1:8001/satellite/orbit?name=ISS%20(ZARYA)&minutes=92&step_seconds=60"
```
