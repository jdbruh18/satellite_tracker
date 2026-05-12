from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from .iss_service import ISSService, PositionHistoryStore
from .models import HealthResponse, OrbitPredictionResponse, PositionHistoryResponse, SatellitePosition
from .orbit_predictor import OrbitPredictor
from .tle_service import DEFAULT_SATELLITE_NAME, TLEService
from .utils import DataValidationError, OrbitPredictionError, TLELookupError, UpstreamServiceError, utc_now


DATA_DIR = Path(__file__).resolve().parent / "data"

router = APIRouter()
history_store = PositionHistoryStore(
    DATA_DIR / "positions.sqlite3",
    legacy_json_path=DATA_DIR / "iss_positions.json",
)
iss_service = ISSService(history_store=history_store)
tle_service = TLEService(cache_path=DATA_DIR / "tle_cache.json")
orbit_predictor = OrbitPredictor()


@router.get("/health", response_model=HealthResponse, tags=["System"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="satellite_tracker", version="1.0.0")


@router.get("/iss/live", response_model=SatellitePosition, tags=["ISS"])
def get_iss_live() -> SatellitePosition:
    try:
        return iss_service.get_live_position()
    except UpstreamServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DataValidationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/iss/history", response_model=PositionHistoryResponse, tags=["ISS"])
def get_iss_history(
    limit: int = Query(default=100, ge=1, le=1000, description="Maximum number of recent positions to return"),
) -> PositionHistoryResponse:
    try:
        positions = iss_service.get_history(limit=limit)
    except DataValidationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return PositionHistoryResponse(count=len(positions), positions=positions)


@router.get("/satellite/orbit", response_model=OrbitPredictionResponse, tags=["Satellites"])
def get_satellite_orbit(
    name: str = Query(default=DEFAULT_SATELLITE_NAME, min_length=1, max_length=120),
    minutes: int = Query(default=92, ge=1, le=1440),
    step_seconds: int = Query(default=60, ge=5, le=600),
    force_refresh: bool = Query(default=False),
) -> OrbitPredictionResponse:
    try:
        tle = tle_service.get_tle(satellite_name=name, force_refresh=force_refresh)
        points = orbit_predictor.predict(tle=tle, minutes=minutes, step_seconds=step_seconds)
    except TLELookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UpstreamServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except DataValidationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OrbitPredictionError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return OrbitPredictionResponse(
        satellite=tle.satellite,
        generated_at=utc_now(),
        tle_fetched_at=tle.fetched_at,
        tle_age_seconds=tle_service.age_seconds(tle),
        tle_is_stale=tle_service.is_stale(tle),
        start_time=points[0].timestamp,
        end_time=points[-1].timestamp,
        minutes=minutes,
        step_seconds=step_seconds,
        points=points,
    )
