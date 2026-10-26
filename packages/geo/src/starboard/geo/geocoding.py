"""Addresses to points, behind one interface (HANDOFF §6, item 2: a free geocoder for now).

`CensusGeocoder` uses the US Census Bureau's batch geocoder, which is free, needs no
key, and takes up to `CENSUS_BATCH_LIMIT` addresses per request; it covers the
United States only (https://geocoding.geo.census.gov/geocoder/Geocoding_Services_API.html).
Answers are cached under `cache/geocode/` by the hash of each address, so a re-upload
asks for nothing it has asked before. Nothing here raises on an address it cannot
place: every address gets an outcome, and the caller sends the unplaced ones to review.
"""

import csv
import hashlib
import io
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import requests

from starboard.solver.graph import LonLat

CENSUS_BATCH_URL = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
# The service's own limit per batch file.
CENSUS_BATCH_LIMIT = 10_000
# The current address ranges; the Census Bureau names its benchmarks this way.
CENSUS_BENCHMARK = "Public_AR_Current"
# A full batch can take minutes on the Census side.
CENSUS_TIMEOUT_S = 600
DEFAULT_GEOCODE_CACHE = Path("cache/geocode")


@dataclass(frozen=True, slots=True)
class Address:
    street: str
    city: str = ""
    state: str = ""
    zip_code: str = ""

    def one_line(self) -> str:
        return ", ".join(
            part for part in (self.street, self.city, self.state, self.zip_code) if part
        )


class GeocodeQuality(StrEnum):
    EXACT = "exact"  # the address matched as written
    INEXACT = "inexact"  # matched after the geocoder changed the address
    AMBIGUOUS = "ambiguous"  # more than one place fits
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class GeocodeOutcome:
    quality: GeocodeQuality
    location: LonLat | None = None
    matched_address: str | None = None


class Geocoder(Protocol):
    def geocode(self, addresses: Sequence[Address]) -> list[GeocodeOutcome]:
        """One outcome per address, in the same order."""
        ...


Post = Callable[[str, bytes], str]  # the batch file in, the service's CSV answer out


def _census_post(url: str, batch: bytes) -> str:
    response = requests.post(
        url,
        data={"benchmark": CENSUS_BENCHMARK},
        files={"addressFile": ("addresses.csv", batch, "text/csv")},
        timeout=CENSUS_TIMEOUT_S,
    )
    response.raise_for_status()
    return response.text


def _outcome(row: list[str]) -> GeocodeOutcome:
    """One answer row: id, input, Match/No_Match/Tie, Exact/Non_Exact, address, "lon,lat", ..."""
    status = row[2].strip() if len(row) > 2 else ""
    if status == "Tie":
        return GeocodeOutcome(GeocodeQuality.AMBIGUOUS)
    if status != "Match" or len(row) < 6:
        return GeocodeOutcome(GeocodeQuality.NOT_FOUND)
    try:
        lon, lat = (float(part) for part in row[5].split(","))
    except ValueError:
        return GeocodeOutcome(GeocodeQuality.NOT_FOUND)
    exact = row[3].strip() == "Exact"
    return GeocodeOutcome(
        GeocodeQuality.EXACT if exact else GeocodeQuality.INEXACT,
        LonLat(lon=lon, lat=lat),
        row[4].strip() or None,
    )


class CensusGeocoder:
    """The US Census batch geocoder, with an on-disk cache of every answer."""

    def __init__(self, cache_dir: Path = DEFAULT_GEOCODE_CACHE, post: Post = _census_post) -> None:
        self.cache_dir = cache_dir
        self._post = post

    def _cache_path(self, address: Address) -> Path:
        key = hashlib.sha256(f"census|{address.one_line().lower()}".encode()).hexdigest()
        return self.cache_dir / key[:2] / f"{key}.json"

    def _cached(self, address: Address) -> GeocodeOutcome | None:
        path = self._cache_path(address)
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        where = data.get("location")
        return GeocodeOutcome(
            GeocodeQuality(data["quality"]),
            None if where is None else LonLat(lon=where[0], lat=where[1]),
            data.get("matched_address"),
        )

    def _store(self, address: Address, outcome: GeocodeOutcome) -> None:
        path = self._cache_path(address)
        path.parent.mkdir(parents=True, exist_ok=True)
        where = outcome.location
        data = {
            "quality": outcome.quality.value,
            "location": None if where is None else [where.lon, where.lat],
            "matched_address": outcome.matched_address,
        }
        path.write_text(json.dumps(data), encoding="utf-8")

    def geocode(self, addresses: Sequence[Address]) -> list[GeocodeOutcome]:
        outcomes: list[GeocodeOutcome | None] = [self._cached(a) for a in addresses]
        missing = [k for k, outcome in enumerate(outcomes) if outcome is None]
        for start in range(0, len(missing), CENSUS_BATCH_LIMIT):
            chunk = missing[start : start + CENSUS_BATCH_LIMIT]
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            for k in chunk:
                a = addresses[k]
                writer.writerow([k, a.street, a.city, a.state, a.zip_code])
            answer = self._post(CENSUS_BATCH_URL, buffer.getvalue().encode())
            for row in csv.reader(io.StringIO(answer)):
                if not row or not row[0].strip().isdigit():
                    continue
                k = int(row[0])
                if k in chunk and outcomes[k] is None:
                    outcome = _outcome(row)
                    outcomes[k] = outcome
                    self._store(addresses[k], outcome)
        # An address the answer left out was not found; it is not cached, so it is asked again.
        return [o if o is not None else GeocodeOutcome(GeocodeQuality.NOT_FOUND) for o in outcomes]


@dataclass(frozen=True, slots=True)
class Geocoded:
    """Stops placed by the geocoder, and the ones it could not place.

    `points` maps stop ids to where the geocoder put them; `inexact` are the ids it
    placed only after changing the address, which a planner should confirm;
    `unplaced` maps the rest to why.
    """

    points: dict[str, LonLat]
    inexact: frozenset[str]
    unplaced: dict[str, GeocodeQuality]
    matched_address: dict[str, str]


def geocode_all(geocoder: Geocoder, addresses: Sequence[tuple[str, Address]]) -> Geocoded:
    """Geocode `(stop_id, address)` pairs in one call; never raises on an address."""
    outcomes = geocoder.geocode([a for _, a in addresses]) if addresses else []
    points: dict[str, LonLat] = {}
    inexact: set[str] = set()
    unplaced: dict[str, GeocodeQuality] = {}
    matched: dict[str, str] = {}
    for (stop_id, _), outcome in zip(addresses, outcomes, strict=True):
        if outcome.location is None:
            unplaced[stop_id] = outcome.quality
            continue
        points[stop_id] = outcome.location
        if outcome.quality is GeocodeQuality.INEXACT:
            inexact.add(stop_id)
        if outcome.matched_address:
            matched[stop_id] = outcome.matched_address
    return Geocoded(points, frozenset(inexact), unplaced, matched)
