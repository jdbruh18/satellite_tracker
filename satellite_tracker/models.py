from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SatellitePosition(BaseModel):
    satellite: str = Field(..., min_length=1, max_length=120)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    timestamp: datetime
    source: str = Field(..., min_length=1)
    altitude_km: Optional[float] = Field(default=None, ge=0.0)


class PositionHistoryResponse(BaseModel):
    count: int = Field(..., ge=0)
    positions: List[SatellitePosition]


class TLEData(BaseModel):
    satellite: str = Field(..., min_length=1, max_length=120)
    line1: str = Field(..., min_length=60, max_length=90)
    line2: str = Field(..., min_length=60, max_length=90)
    fetched_at: datetime
    source_url: str = Field(..., min_length=1)


class OrbitPoint(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    altitude_km: float
    timestamp: datetime


class OrbitPredictionResponse(BaseModel):
    satellite: str
    generated_at: datetime
    tle_fetched_at: datetime
    tle_age_seconds: float = Field(..., ge=0.0)
    tle_is_stale: bool
    start_time: datetime
    end_time: datetime
    minutes: int = Field(..., ge=1)
    step_seconds: int = Field(..., ge=1)
    points: List[OrbitPoint]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
