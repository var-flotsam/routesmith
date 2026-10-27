"""Read a stop CSV into stops in their current order.

Required columns: `stop_id` and `current_sequence`, and a way to place each stop:
`lon` and `lat`, or an address in `address` (or `house_number` and `street`), with
optional `city`, `state` and `zip`. A row with lon/lat is placed by them; a row
with only an address waits for the geocoder (`StopFile.unlocated`).

Optional: `street`, which breaks ties when a stop is about equally close to two
streets, and `route_id`, which names the truck route a stop is on today when the
area is served by several trucks; `current_sequence` then orders stops within
their route. A row that cannot be read becomes a rejected row with a reason;
reading never raises on the file's contents. That includes a row holding the NUL
character anywhere (no database stores it in text, and a file with one is damaged),
a row too long for the csv module to read, and a stop id, route id or street longer
than the stops table holds.
"""

import csv
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from starboard.geo.geocoding import Address
from starboard.geo.snapping import StopPoint
from starboard.solver.graph import LonLat

REQUIRED_COLUMNS = ("stop_id", "current_sequence")
# The longest of each the stops table stores; a longer one is a rejected row.
MAX_STOP_ID_LENGTH = 100
MAX_ROUTE_ID_LENGTH = 100
MAX_STREET_LENGTH = 200
_NUL = "\x00"


@dataclass(frozen=True, slots=True)
class RejectedRow:
    line_number: int
    reason: str


@dataclass(frozen=True, slots=True)
class UnlocatedStop:
    """A stop given by address only; the geocoder places it."""

    stop_id: str
    address: Address
    street: str | None = None


@dataclass(frozen=True, slots=True)
class StopFile:
    """The stops in current order.

    `stops` are placed by lon/lat; `unlocated` wait for the geocoder; `order` is
    every stop id in current order, placed or not. `route_of` maps stop ids to
    route ids when the file has them.
    """

    stops: tuple[StopPoint, ...]
    rejected: tuple[RejectedRow, ...]
    route_of: dict[str, str] = field(default_factory=dict)
    unlocated: tuple[UnlocatedStop, ...] = ()
    order: tuple[str, ...] = ()


def _cell(row: Mapping[str, str | None], name: str) -> str:
    return (row.get(name) or "").strip()


def _address(row: Mapping[str, str | None]) -> Address | None:
    line = _cell(row, "address") or " ".join(
        part for part in (_cell(row, "house_number"), _cell(row, "street")) if part
    )
    if not line:
        return None
    return Address(line, _cell(row, "city"), _cell(row, "state"), _cell(row, "zip"))


def _holds_nul(row: Mapping[str | None, str | list[str] | None]) -> bool:
    # Cells past the header's columns come as a list under the key None.
    return any(
        _NUL in (value if isinstance(value, str) else "".join(value))
        for value in row.values()
        if value is not None
    )


def _too_long(row: Mapping[str, str | None]) -> str | None:
    for column, longest in (
        ("stop_id", MAX_STOP_ID_LENGTH),
        ("route_id", MAX_ROUTE_ID_LENGTH),
        ("street", MAX_STREET_LENGTH),
    ):
        if len(_cell(row, column)) > longest:
            return f"{column} is longer than {longest} characters"
    return None


def _parse_row(row: Mapping[str, str | None]) -> tuple[int, StopPoint | UnlocatedStop] | str:
    stop_id = _cell(row, "stop_id")
    if not stop_id:
        return "no stop_id"
    street = _cell(row, "street") or None
    has_point = bool(_cell(row, "lon") or _cell(row, "lat"))
    try:
        sequence = int(_cell(row, "current_sequence"))
        if has_point:
            lon, lat = float(_cell(row, "lon")), float(_cell(row, "lat"))
    except ValueError:
        return "current_sequence, lon or lat is not a number"
    if not has_point:
        address = _address(row)
        if address is None:
            return "no lon/lat and no address"
        return sequence, UnlocatedStop(stop_id, address, street)
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        return "lon or lat is out of range"
    return sequence, StopPoint(stop_id, LonLat(lon=lon, lat=lat), street=street)


def read_stop_rows(handle: Iterable[str]) -> StopFile:
    """Read stop rows from text lines, such as an open file or an uploaded body."""
    reader = csv.DictReader(handle)
    columns = set(reader.fieldnames or [])
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if not ({"lon", "lat"} <= columns or "address" in columns or "street" in columns):
        missing.append("lon and lat, or an address")
    if missing:
        return StopFile((), (RejectedRow(1, f"missing columns: {', '.join(missing)}"),))
    with_routes = "route_id" in columns
    ordered: list[tuple[int, int, StopPoint | UnlocatedStop]] = []
    rejected: list[RejectedRow] = []
    route_of: dict[str, str] = {}
    seen: set[str] = set()
    rows = iter(reader)
    line_number = 1
    while True:
        line_number += 1
        try:
            row = next(rows)
        except StopIteration:
            break
        except csv.Error as error:  # such as a field over the csv module's size limit
            rejected.append(RejectedRow(line_number, f"unreadable: {error}"))
            continue
        if _holds_nul(row):
            rejected.append(RejectedRow(line_number, "holds a NUL character"))
            continue
        if (too_long := _too_long(row)) is not None:
            rejected.append(RejectedRow(line_number, too_long))
            continue
        parsed = _parse_row(row)
        if isinstance(parsed, str):
            rejected.append(RejectedRow(line_number, parsed))
            continue
        sequence, stop = parsed
        if stop.stop_id in seen:
            rejected.append(RejectedRow(line_number, f"duplicate stop_id {stop.stop_id}"))
            continue
        route_id = _cell(row, "route_id")
        if with_routes and not route_id:
            rejected.append(RejectedRow(line_number, "no route_id"))
            continue
        seen.add(stop.stop_id)
        if route_id:
            route_of[stop.stop_id] = route_id
        ordered.append((sequence, line_number, stop))
    ordered.sort(key=lambda item: item[:2])
    every = [stop for _, _, stop in ordered]
    return StopFile(
        tuple(s for s in every if isinstance(s, StopPoint)),
        tuple(rejected),
        route_of,
        tuple(s for s in every if isinstance(s, UnlocatedStop)),
        tuple(s.stop_id for s in every),
    )


def read_stop_file(path: Path) -> StopFile:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return read_stop_rows(handle)
