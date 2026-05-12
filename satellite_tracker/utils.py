from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SatelliteTrackerError(Exception):
    """Base exception for expected application failures."""


class UpstreamServiceError(SatelliteTrackerError):
    """Raised when an external satellite data provider fails."""


class DataValidationError(SatelliteTrackerError):
    """Raised when received or stored data cannot be trusted."""


class TLELookupError(SatelliteTrackerError):
    """Raised when a requested satellite TLE cannot be found."""


class OrbitPredictionError(SatelliteTrackerError):
    """Raised when orbit propagation fails."""


class InterProcessFileLock:
    def __init__(
        self,
        path: Path,
        timeout_seconds: float = 30.0,
        stale_seconds: float = 120.0,
        poll_seconds: float = 0.1,
    ) -> None:
        self.path = path
        self.timeout_seconds = timeout_seconds
        self.stale_seconds = stale_seconds
        self.poll_seconds = poll_seconds
        self._locked = False

    def __enter__(self) -> "InterProcessFileLock":
        ensure_directory(self.path.parent)
        deadline = time.monotonic() + self.timeout_seconds

        while True:
            try:
                file_descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(file_descriptor, "w", encoding="utf-8") as file_obj:
                    file_obj.write(f"{os.getpid()} {time.time()}\n")
                self._locked = True
                return self
            except FileExistsError:
                self._remove_stale_lock()
                if time.monotonic() >= deadline:
                    raise DataValidationError(f"Timed out waiting for lock: {self.path}")
                time.sleep(self.poll_seconds)
            except OSError as exc:
                raise DataValidationError(f"Could not acquire lock: {self.path}") from exc

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if not self._locked:
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        finally:
            self._locked = False

    def _remove_stale_lock(self) -> None:
        try:
            lock_age = time.time() - self.path.stat().st_mtime
        except FileNotFoundError:
            return
        except OSError:
            return

        if lock_age <= self.stale_seconds:
            return

        try:
            self.path.unlink()
        except OSError:
            pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_unix_timestamp(value: Any) -> datetime:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError) as exc:
        raise DataValidationError(f"Invalid Unix timestamp: {value!r}") from exc


def normalize_longitude(value: float) -> float:
    normalized = ((float(value) + 180.0) % 360.0) - 180.0
    if normalized == -180.0 and value > 0:
        return 180.0
    return normalized


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as file_obj:
            return json.load(file_obj)
    except json.JSONDecodeError as exc:
        raise DataValidationError(f"JSON file is corrupted: {path}") from exc
    except OSError as exc:
        raise DataValidationError(f"Could not read JSON file: {path}") from exc


def atomic_write_json(path: Path, payload: Any) -> None:
    ensure_directory(path.parent)
    file_descriptor = None
    temp_path = None

    try:
        file_descriptor, temp_name = tempfile.mkstemp(
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            text=True,
        )
        temp_path = Path(temp_name)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as file_obj:
            file_descriptor = None
            json.dump(payload, file_obj, ensure_ascii=True, indent=2, default=_json_default)
            file_obj.write("\n")
        os.replace(temp_path, path)
    except OSError as exc:
        raise DataValidationError(f"Could not write JSON file: {path}") from exc
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")
