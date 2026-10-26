"""What every export is made from: one run's optimized routes and the stops they serve.

The API builds this from a run's stored report and the upload's stops; the exports
read nothing else, so the same run always gives the same files.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StopInfo:
    stop_id: str
    street: str | None
    lon: float | None
    lat: float | None
    current_route: str | None
    current_sequence: int


@dataclass(frozen=True, slots=True)
class Step:
    """One line of a route sheet, as `starboard.solver.route_sheet` produces it."""

    action: str
    street: str | None
    distance_m: float
    stop_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TruckRoute:
    """One optimized route: stops in collection order, the driven path, and its steps."""

    order: tuple[str, ...]
    path: tuple[tuple[float, float], ...]  # (lon, lat)
    steps: tuple[Step, ...]
    route_time_s: float
    distance_m: float


@dataclass(frozen=True, slots=True)
class RunExport:
    route_name: str
    osm_snapshot: str | None
    routes: tuple[TruckRoute, ...]
    stops: dict[str, StopInfo]
