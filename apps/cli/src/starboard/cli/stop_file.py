"""Read a stop CSV in the demo layout into stops in their current order.

Required columns: `stop_id`, `current_sequence`, `lon`, `lat`. Optional:
`street`, which breaks ties when a stop is about equally close to two
streets. A row that cannot be read becomes a rejected row with a reason;
reading never raises on the file's contents.
"""

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from starboard.geo.snapping import StopPoint
from starboard.solver.graph import LonLat

REQUIRED_COLUMNS = ("stop_id", "current_sequence", "lon", "lat")


@dataclass(frozen=True, slots=True)
class RejectedRow:
    line_number: int
    reason: str


@dataclass(frozen=True, slots=True)
class StopFile:
    stops: tuple[StopPoint, ...]
    rejected: tuple[RejectedRow, ...]


def _parse_row(row: dict[str, str]) -> tuple[int, StopPoint] | str:
    stop_id = (row.get("stop_id") or "").strip()
    if not stop_id:
        return "no stop_id"
    try:
        sequence = int(row["current_sequence"])
        lon, lat = float(row["lon"]), float(row["lat"])
    except (TypeError, ValueError):
        return "current_sequence, lon or lat is not a number"
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        return "lon or lat is out of range"
    street = (row.get("street") or "").strip() or None
    return sequence, StopPoint(stop_id, LonLat(lon=lon, lat=lat), street=street)


def read_stop_file(path: Path) -> StopFile:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            return StopFile((), (RejectedRow(1, f"missing columns: {', '.join(missing)}"),))
        ordered: list[tuple[int, int, StopPoint]] = []
        rejected: list[RejectedRow] = []
        seen: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            parsed = _parse_row(row)
            if isinstance(parsed, str):
                rejected.append(RejectedRow(line_number, parsed))
                continue
            sequence, stop = parsed
            if stop.stop_id in seen:
                rejected.append(RejectedRow(line_number, f"duplicate stop_id {stop.stop_id}"))
                continue
            seen.add(stop.stop_id)
            ordered.append((sequence, line_number, stop))
    ordered.sort(key=lambda item: item[:2])
    return StopFile(tuple(stop for _, _, stop in ordered), tuple(rejected))
