from __future__ import annotations

import logging
import sqlite3
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import List

import requests
from pydantic import ValidationError

from .models import SatellitePosition
from .utils import (
    DataValidationError,
    InterProcessFileLock,
    UpstreamServiceError,
    ensure_directory,
    ensure_utc,
    normalize_longitude,
    parse_unix_timestamp,
    read_json_file,
    utc_now,
)

logger = logging.getLogger(__name__)


OPEN_NOTIFY_ISS_URL = "http://api.open-notify.org/iss-now.json"


class PositionHistoryStore:
    def __init__(self, path: Path, max_positions: int = 1000, legacy_json_path: Path | None = None) -> None:
        self.path = path
        self.max_positions = max_positions
        self._lock = Lock()
        self.legacy_json_path = legacy_json_path
        self._initialize()

    def append(self, position: SatellitePosition) -> None:
        with self._lock:
            with self._connect() as connection:
                self._insert_unlocked(connection, position)
                self._trim_unlocked(connection)

    def list_recent(self, limit: int = 100) -> List[SatellitePosition]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT satellite, latitude, longitude, timestamp, source, altitude_km
                FROM positions
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        positions = [self._row_to_position(row) for row in rows]
        positions.reverse()
        return positions

    def latest(self) -> SatellitePosition | None:
        recent = self.list_recent(limit=1)
        return recent[-1] if recent else None

    def _connect(self) -> sqlite3.Connection:
        ensure_directory(self.path.parent)
        connection = sqlite3.connect(str(self.path), timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    satellite TEXT NOT NULL,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    altitude_km REAL,
                    UNIQUE (satellite, timestamp)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_positions_timestamp
                ON positions (timestamp DESC)
                """
            )
            self._migrate_legacy_json_unlocked(connection)

    def _migrate_legacy_json_unlocked(self, connection: sqlite3.Connection) -> None:
        if self.legacy_json_path is None or not self.legacy_json_path.exists():
            return

        existing_count = connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        if existing_count:
            return

        try:
            records = read_json_file(self.legacy_json_path, default=[])
        except DataValidationError:
            logger.warning("Ignoring unreadable legacy ISS history file: %s", self.legacy_json_path, exc_info=True)
            return
        if not isinstance(records, list):
            logger.warning("Ignoring malformed legacy ISS history file: %s", self.legacy_json_path)
            return

        for record in records:
            try:
                self._insert_unlocked(connection, SatellitePosition(**record))
            except (TypeError, ValidationError):
                logger.warning("Skipping invalid ISS history record: %r", record, exc_info=True)

        self._trim_unlocked(connection)

    def _insert_unlocked(self, connection: sqlite3.Connection, position: SatellitePosition) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO positions (satellite, latitude, longitude, timestamp, source, altitude_km)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                position.satellite,
                position.latitude,
                position.longitude,
                ensure_utc(position.timestamp).isoformat(),
                position.source,
                position.altitude_km,
            ),
        )

    def _trim_unlocked(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM positions
            WHERE id NOT IN (
                SELECT id
                FROM positions
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
            )
            """,
            (self.max_positions,),
        )

    def _row_to_position(self, row: sqlite3.Row) -> SatellitePosition:
        return SatellitePosition(
            satellite=row["satellite"],
            latitude=row["latitude"],
            longitude=row["longitude"],
            timestamp=row["timestamp"],
            source=row["source"],
            altitude_km=row["altitude_km"],
        )


class ISSService:
    def __init__(
        self,
        history_store: PositionHistoryStore,
        api_url: str = OPEN_NOTIFY_ISS_URL,
        timeout_seconds: float = 15.0,
        poll_interval_seconds: float = 5.0,
        refresh_lock_path: Path | None = None,
    ) -> None:
        self.history_store = history_store
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.refresh_lock_path = refresh_lock_path or history_store.path.with_suffix(".refresh.lock")
        self._latest_lock = Lock()
        self._latest_position = history_store.latest()

    def fetch_live_position(self) -> SatellitePosition:
        try:
            response = requests.get(self.api_url, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.Timeout as exc:
            raise UpstreamServiceError("Timed out fetching ISS live position") from exc
        except requests.RequestException as exc:
            raise UpstreamServiceError("Failed to fetch ISS live position") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise DataValidationError("Open Notify returned invalid JSON") from exc

        position = self._parse_open_notify_payload(payload)
        self.history_store.append(position)
        self._set_latest(position)
        return position

    def refresh_if_due(self) -> SatellitePosition:
        latest = self.history_store.latest()
        if latest and self._is_recent(latest):
            self._set_latest(latest)
            return latest

        try:
            with InterProcessFileLock(
                self.refresh_lock_path,
                timeout_seconds=1.0,
                stale_seconds=max(60.0, self.timeout_seconds * 4),
            ):
                latest = self.history_store.latest()
                if latest and self._is_recent(latest):
                    self._set_latest(latest)
                    return latest
                try:
                    return self.fetch_live_position()
                except UpstreamServiceError:
                    if latest is not None:
                        self._set_latest(latest)
                        return latest
                    raise
        except DataValidationError:
            if latest is not None:
                self._set_latest(latest)
                return latest
            raise

    def get_live_position(self) -> SatellitePosition:
        latest_from_store = self.history_store.latest()
        with self._latest_lock:
            if latest_from_store and (
                self._latest_position is None
                or ensure_utc(latest_from_store.timestamp) > ensure_utc(self._latest_position.timestamp)
            ):
                self._latest_position = latest_from_store

            if self._latest_position is None:
                raise UpstreamServiceError("No ISS position is available yet")

            return self._latest_position

    def get_history(self, limit: int = 100) -> List[SatellitePosition]:
        return self.history_store.list_recent(limit=limit)

    def _set_latest(self, position: SatellitePosition) -> None:
        with self._latest_lock:
            self._latest_position = position

    def _is_recent(self, position: SatellitePosition) -> bool:
        age = utc_now() - ensure_utc(position.timestamp)
        return age <= timedelta(seconds=self.poll_interval_seconds)

    def _parse_open_notify_payload(self, payload: dict) -> SatellitePosition:
        if payload.get("message") != "success":
            raise UpstreamServiceError("Open Notify did not return a successful response")

        iss_position = payload.get("iss_position")
        if not isinstance(iss_position, dict):
            raise DataValidationError("Open Notify response is missing iss_position")

        try:
            latitude = float(iss_position["latitude"])
            longitude = normalize_longitude(float(iss_position["longitude"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise DataValidationError("Open Notify response contains invalid coordinates") from exc

        timestamp = parse_unix_timestamp(payload.get("timestamp"))

        try:
            return SatellitePosition(
                satellite="ISS",
                latitude=latitude,
                longitude=longitude,
                timestamp=timestamp,
                source=self.api_url,
                altitude_km=None,
            )
        except ValidationError as exc:
            raise DataValidationError("Open Notify response failed position validation") from exc
