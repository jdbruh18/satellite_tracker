from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from skyfield.api import EarthSatellite, load, wgs84

from .models import OrbitPoint, TLEData
from .utils import OrbitPredictionError, ensure_utc, normalize_longitude, utc_now


class OrbitPredictor:
    def __init__(self) -> None:
        self._timescale = load.timescale()

    def predict(
        self,
        tle: TLEData,
        minutes: int = 92,
        step_seconds: int = 60,
        start_time: datetime | None = None,
    ) -> List[OrbitPoint]:
        if minutes < 1:
            raise OrbitPredictionError("Prediction window must be at least 1 minute")
        if step_seconds < 1:
            raise OrbitPredictionError("Prediction step must be at least 1 second")

        start = ensure_utc(start_time or utc_now())
        end = start + timedelta(minutes=minutes)
        timestamps = self._build_timestamps(start, end, step_seconds)

        try:
            satellite = EarthSatellite(tle.line1, tle.line2, tle.satellite, self._timescale)
            times = self._timescale.from_datetimes(timestamps)
            geocentric = satellite.at(times)
            subpoints = wgs84.subpoint(geocentric)
        except Exception as exc:
            raise OrbitPredictionError(f"Could not propagate orbit for {tle.satellite}") from exc

        points: list[OrbitPoint] = []
        for timestamp, latitude, longitude, altitude in zip(
            timestamps,
            subpoints.latitude.degrees,
            subpoints.longitude.degrees,
            subpoints.elevation.km,
        ):
            points.append(
                OrbitPoint(
                    latitude=float(latitude),
                    longitude=normalize_longitude(float(longitude)),
                    altitude_km=float(altitude),
                    timestamp=timestamp,
                )
            )
        return points

    @staticmethod
    def _build_timestamps(start: datetime, end: datetime, step_seconds: int) -> List[datetime]:
        timestamps: list[datetime] = []
        current = start
        step = timedelta(seconds=step_seconds)

        while current <= end:
            timestamps.append(current)
            current += step

        if timestamps[-1] != end:
            timestamps.append(end)

        return timestamps
