"""Fetch the drivable street network for a bounding box from OpenStreetMap.

Networks are cached on disk under `cache/osm/` (git-ignored) as GraphML with
a JSON sidecar recording the bounding box, fetch time and the OSM database
timestamp, so every run can state which OSM snapshot it used.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any  # OSMnx graphs carry untyped attribute dicts

import networkx as nx
import osmnx as ox
import requests

from starboard.geo.projection import EARTH_MEAN_RADIUS_M
from starboard.geo.state_graph import build_state_graph
from starboard.solver.graph import LonLat, StateGraph, StreetSegment

DEFAULT_CACHE_DIR = Path("cache/osm")
_KPH_PER_MPH = 1.609344  # international mile: https://www.nist.gov/pml/us-surveyfoot/revised-unit-conversion-factors


@dataclass(frozen=True, slots=True)
class BoundingBox:
    west: float
    south: float
    east: float
    north: float

    def __post_init__(self) -> None:
        if not (-180 <= self.west < self.east <= 180 and -90 <= self.south < self.north <= 90):
            raise ValueError(f"not a valid bounding box: {self}")

    def cache_key(self) -> str:
        text = ",".join(f"{v:.6f}" for v in (self.west, self.south, self.east, self.north))
        return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class NetworkSnapshot:
    bbox: BoundingBox
    fetched_at: str
    osm_timestamp: str | None


def parse_speed_kph(value: object) -> float | None:
    """OSM `maxspeed` as km/h: '25 mph', '40', or a list of those (lowest wins)."""
    if isinstance(value, list):
        speeds = [s for s in (parse_speed_kph(v) for v in value) if s is not None]
        return min(speeds) if speeds else None
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kmh|kph)?\s*", value)
    if match is None:
        return None
    speed = float(match.group(1))
    return speed * _KPH_PER_MPH if match.group(2) == "mph" else speed


def _first(value: object) -> object:
    return value[0] if isinstance(value, list) and value else value


def _edge_geometry(
    graph: nx.MultiDiGraph[Any], u: int, v: int, data: dict[str, Any]
) -> tuple[LonLat, ...]:
    geometry = data.get("geometry")
    if geometry is not None:
        return tuple(LonLat(lon=x, lat=y) for x, y in geometry.coords)
    return (
        LonLat(lon=graph.nodes[u]["x"], lat=graph.nodes[u]["y"]),
        LonLat(lon=graph.nodes[v]["x"], lat=graph.nodes[v]["y"]),
    )


def segments_from_osmnx(graph: nx.MultiDiGraph[Any]) -> list[StreetSegment]:
    """Collapse an OSMnx directed graph into segments with allowed directions.

    OSMnx stores a two-way street as a pair of opposite directed edges with
    mirrored geometry, and a one-way street as a single edge. Each pair
    becomes one segment allowing both directions.
    """
    segments: dict[str, StreetSegment] = {}
    by_shape: dict[tuple[frozenset[int], str, float], str] = {}
    for u, v, key, data in sorted(graph.edges(keys=True, data=True), key=lambda e: e[:3]):
        geometry = _edge_geometry(graph, u, v, data)
        shape = (frozenset((u, v)), str(data.get("osmid")), round(float(data["length"]), 1))
        existing_id = by_shape.get(shape)
        if existing_id is not None:
            existing = segments[existing_id]
            if existing.geometry == tuple(reversed(geometry)):
                segments[existing_id] = StreetSegment(
                    **{**_fields(existing), "reverse_allowed": True}
                )
                continue
        segment_id = f"{u}-{v}-{key}"
        name = _first(data.get("name"))
        segments[segment_id] = StreetSegment(
            segment_id=segment_id,
            from_node=int(u),
            to_node=int(v),
            geometry=geometry,
            length_m=float(data["length"]),
            name=name if isinstance(name, str) else None,
            forward_allowed=True,
            reverse_allowed=False,
            speed_limit_kph=parse_speed_kph(data.get("maxspeed")),
        )
        by_shape.setdefault(shape, segment_id)
    return list(segments.values())


def _fields(segment: StreetSegment) -> dict[str, Any]:
    return {name: getattr(segment, name) for name in StreetSegment.__slots__}


def _overpass_timestamp() -> str | None:
    """The OSM database timestamp the Overpass server is serving right now."""
    try:
        response = requests.get(
            ox.settings.overpass_url + "/interpreter",
            params={"data": "[out:json];out;"},
            timeout=ox.settings.requests_timeout,
        )
        response.raise_for_status()
        timestamp = response.json().get("osm3s", {}).get("timestamp_osm_base")
    except (requests.RequestException, ValueError):
        return None
    return timestamp if isinstance(timestamp, str) else None


def fetch_network(bbox: BoundingBox, cache_dir: Path = DEFAULT_CACHE_DIR) -> StateGraph:
    """The state graph for `bbox`, from the on-disk cache or a fresh Overpass fetch."""
    graphml = cache_dir / f"{bbox.cache_key()}.graphml"
    sidecar = graphml.with_suffix(".json")
    if graphml.exists() and sidecar.exists():
        graph = ox.load_graphml(graphml)
        snapshot = json.loads(sidecar.read_text(encoding="utf-8"))
    else:
        cache_dir.mkdir(parents=True, exist_ok=True)
        osm_timestamp = _overpass_timestamp()
        graph = ox.graph_from_bbox(
            (bbox.west, bbox.south, bbox.east, bbox.north),
            network_type="drive",
            truncate_by_edge=True,
        )
        ox.save_graphml(graph, graphml)
        snapshot = asdict(
            NetworkSnapshot(
                bbox=bbox,
                fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
                osm_timestamp=osm_timestamp,
            )
        )
        sidecar.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    return build_state_graph(
        segments_from_osmnx(graph),
        osm_snapshot=snapshot.get("osm_timestamp") or snapshot.get("fetched_at"),
    )


def bbox_around(points: Iterable[LonLat], margin_m: float) -> BoundingBox:
    """The smallest box containing `points`, grown by `margin_m` on every side."""
    lons, lats = zip(*((p.lon, p.lat) for p in points), strict=True)
    dlat = math.degrees(margin_m / EARTH_MEAN_RADIUS_M)
    dlon = dlat / math.cos(math.radians(sum(lats) / len(lats)))
    return BoundingBox(min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat)
