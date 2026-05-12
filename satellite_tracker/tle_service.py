from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import Iterable, List

import requests
from pydantic import ValidationError

from .models import TLEData
from .utils import (
    DataValidationError,
    InterProcessFileLock,
    TLELookupError,
    UpstreamServiceError,
    atomic_write_json,
    ensure_utc,
    model_to_dict,
    read_json_file,
    utc_now,
)

logger = logging.getLogger(__name__)


DEFAULT_CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=tle"
DEFAULT_SATELLITE_NAME = "ISS (ZARYA)"


class TLEService:
    def __init__(
        self,
        cache_path: Path,
        source_url: str = DEFAULT_CELESTRAK_URL,
        timeout_seconds: float = 12.0,
        cache_ttl: timedelta = timedelta(hours=6),
        max_stale_age: timedelta = timedelta(days=3),
    ) -> None:
        self.cache_path = cache_path
        self.source_url = source_url
        self.timeout_seconds = timeout_seconds
        self.cache_ttl = cache_ttl
        self.max_stale_age = max_stale_age
        self._refresh_lock = Lock()

    def get_tle(self, satellite_name: str = DEFAULT_SATELLITE_NAME, force_refresh: bool = False) -> TLEData:
        entries = self.fetch_all(force_refresh=force_refresh)
        query = satellite_name.strip()
        match = self._find_match(entries, query)
        if match is None:
            available = ", ".join(entry.satellite for entry in entries[:8])
            raise TLELookupError(
                f"Satellite {satellite_name!r} was not found in the CelesTrak stations feed. "
                f"Available examples: {available}"
            )
        return match

    def fetch_all(self, force_refresh: bool = False) -> List[TLEData]:
        if not force_refresh:
            cached = self._load_cache(require_fresh=True)
            if cached:
                return cached

        with self._refresh_lock:
            with InterProcessFileLock(
                self.cache_path.with_suffix(f"{self.cache_path.suffix}.lock"),
                timeout_seconds=30.0,
                stale_seconds=max(120.0, self.timeout_seconds * 4),
            ):
                if not force_refresh:
                    cached = self._load_cache(require_fresh=True)
                    if cached:
                        return cached

                return self._fetch_and_cache()

    def is_stale(self, tle: TLEData) -> bool:
        return utc_now() - ensure_utc(tle.fetched_at) > self.cache_ttl

    def age_seconds(self, tle: TLEData) -> float:
        return max(0.0, (utc_now() - ensure_utc(tle.fetched_at)).total_seconds())

    def _fetch_and_cache(self) -> List[TLEData]:
        try:
            response = requests.get(self.source_url, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.Timeout as exc:
            return self._load_usable_stale_cache("Timed out fetching TLE data from CelesTrak", exc)
        except requests.RequestException as exc:
            return self._load_usable_stale_cache("Failed to fetch TLE data from CelesTrak", exc)

        entries = self._parse_tle_text(response.text)
        if not entries:
            raise DataValidationError("CelesTrak returned no TLE records")

        atomic_write_json(self.cache_path, [model_to_dict(entry) for entry in entries])
        return entries

    def _load_usable_stale_cache(self, message: str, exc: Exception) -> List[TLEData]:
        stale_cache = self._load_cache(require_fresh=False)
        if not stale_cache:
            raise UpstreamServiceError(message) from exc

        newest_fetch_time = max(ensure_utc(entry.fetched_at) for entry in stale_cache)
        age = utc_now() - newest_fetch_time
        if age <= self.max_stale_age:
            logger.warning("%s; using stale TLE cache from %s", message, newest_fetch_time)
            return stale_cache

        raise UpstreamServiceError(
            f"{message}; cached TLE data is too old to use safely "
            f"({age.total_seconds() / 3600:.1f} hours old)"
        ) from exc

    def _load_cache(self, require_fresh: bool) -> List[TLEData]:
        try:
            records = read_json_file(self.cache_path, default=[])
        except DataValidationError:
            logger.warning("Ignoring unreadable TLE cache at %s", self.cache_path, exc_info=True)
            return []

        if not isinstance(records, list):
            logger.warning("Ignoring malformed TLE cache at %s", self.cache_path)
            return []

        entries: list[TLEData] = []
        for record in records:
            try:
                entries.append(TLEData(**record))
            except (TypeError, ValidationError):
                logger.warning("Skipping invalid TLE cache record: %r", record, exc_info=True)

        if not entries:
            return []

        if require_fresh:
            newest_fetch_time = max(ensure_utc(entry.fetched_at) for entry in entries)
            if utc_now() - newest_fetch_time > self.cache_ttl:
                return []

        return entries

    def _parse_tle_text(self, text: str) -> List[TLEData]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        fetched_at = utc_now()
        entries: list[TLEData] = []
        index = 0

        while index <= len(lines) - 3:
            name = lines[index]
            line1 = lines[index + 1]
            line2 = lines[index + 2]

            if line1.startswith("1 ") and line2.startswith("2 "):
                try:
                    entries.append(
                        TLEData(
                            satellite=name,
                            line1=line1,
                            line2=line2,
                            fetched_at=fetched_at,
                            source_url=self.source_url,
                        )
                    )
                except ValidationError:
                    logger.warning("Skipping invalid TLE set for %s", name, exc_info=True)
                index += 3
            else:
                index += 1

        return entries

    def _find_match(self, entries: Iterable[TLEData], query: str) -> TLEData | None:
        normalized_query = self._normalize(query)
        query_is_norad_id = query.isdigit()

        best_partial_match: TLEData | None = None
        for entry in entries:
            normalized_name = self._normalize(entry.satellite)
            norad_id = entry.line1[2:7].strip()

            if query_is_norad_id and query == norad_id:
                return entry

            if normalized_query == normalized_name:
                return entry

            if normalized_query in {"iss", "international space station"} and normalized_name.startswith("iss"):
                return entry

            if normalized_query and normalized_query in normalized_name and best_partial_match is None:
                best_partial_match = entry

        return best_partial_match

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(
            value.lower()
            .replace("(", " ")
            .replace(")", " ")
            .replace("-", " ")
            .replace("_", " ")
            .split()
        )
