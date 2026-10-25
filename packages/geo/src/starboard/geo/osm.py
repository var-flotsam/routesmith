"""Fetch the drivable street network for a bounding box from OpenStreetMap.

Networks are cached on disk under `cache/osm/` (git-ignored) as GraphML with
a JSON sidecar recording the bounding box, fetch time and the OSM database
timestamp, so every run can state which OSM snapshot it used. Turn
restriction relations, which OSMnx does not keep, are fetched from Overpass
separately and cached beside the network.
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

from starboard.geo.extract import clip_extract, extract_timestamp
from starboard.geo.projection import EARTH_MEAN_RADIUS_M
from starboard.geo.state_graph import RestrictionKind, TurnRestriction, build_state_graph
from starboard.solver.graph import LonLat, StateGraph, StreetSegment

DEFAULT_CACHE_DIR = Path("cache/osm")

# Controlled-access roads, with no driveways or curbside carts:
# https://wiki.openstreetmap.org/wiki/Tag:highway%3Dmotorway and
# https://wiki.openstreetmap.org/wiki/Tag:highway%3Dmotorway_link
UNSERVICEABLE_ROAD_CLASSES = frozenset({"motorway", "motorway_link"})
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
        road_class = _first(data.get("highway"))
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
            road_class=road_class if isinstance(road_class, str) else None,
            serviceable=road_class not in UNSERVICEABLE_ROAD_CLASSES,
            osm_way_ids=_way_ids(data.get("osmid")),
        )
        by_shape.setdefault(shape, segment_id)
    return list(segments.values())


def _way_ids(value: object) -> tuple[int, ...]:
    values = value if isinstance(value, list) else [value]
    return tuple(sorted(int(v) for v in values if isinstance(v, int | str) and str(v).isdigit()))


def _fields(segment: StreetSegment) -> dict[str, Any]:
    return {name: getattr(segment, name) for name in StreetSegment.__slots__}


def _osm_timestamp(responses: Iterable[Path]) -> str | None:
    """The oldest OSM database timestamp among Overpass responses, if any record one."""
    timestamps: list[str] = []
    for response in responses:
        try:
            body = json.loads(response.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        timestamp = (
            body.get("osm3s", {}).get("timestamp_osm_base") if isinstance(body, dict) else None
        )
        if isinstance(timestamp, str):
            timestamps.append(timestamp)
    return min(timestamps) if timestamps else None


def restrictions_from_overpass(body: dict[str, Any]) -> tuple[list[TurnRestriction], int]:
    """Turn restrictions from an Overpass `out body` response of restriction relations.

    Returns the restrictions this model can apply and a count of those it
    cannot: restrictions through a way rather than a node, or with a
    missing or unknown member or value. `restriction:hgv` wins over
    `restriction` where both are tagged, since collection trucks are HGVs.
    """
    restrictions: list[TurnRestriction] = []
    unsupported = 0
    for element in body.get("elements", []):
        if element.get("type") != "relation":
            continue
        tags = element.get("tags", {})
        value = str(tags.get("restriction:hgv") or tags.get("restriction") or "")
        kind = (
            RestrictionKind.PROHIBITORY
            if value.startswith("no_")
            else RestrictionKind.MANDATORY
            if value.startswith("only_")
            else None
        )
        members = element.get("members", [])
        from_ways = [
            m["ref"] for m in members if m.get("role") == "from" and m.get("type") == "way"
        ]
        to_ways = [m["ref"] for m in members if m.get("role") == "to" and m.get("type") == "way"]
        via_nodes = [
            m["ref"] for m in members if m.get("role") == "via" and m.get("type") == "node"
        ]
        if kind is None or len(from_ways) != 1 or len(to_ways) != 1 or len(via_nodes) != 1:
            unsupported += 1
            continue
        restrictions.append(TurnRestriction(from_ways[0], via_nodes[0], to_ways[0], kind))
    return restrictions, unsupported


def _fetch_restriction_relations(bbox: BoundingBox) -> dict[str, Any]:
    query = (
        f"[out:json][timeout:{ox.settings.requests_timeout}];"
        f'rel["type"="restriction"]({bbox.south},{bbox.west},{bbox.north},{bbox.east});'
        "out body;"
    )
    response = requests.post(
        ox.settings.overpass_url + "/interpreter",
        data={"data": query},
        headers={"User-Agent": ox.settings.http_user_agent},
        timeout=ox.settings.requests_timeout,
    )
    response.raise_for_status()
    body: dict[str, Any] = response.json()
    return body


def fetch_network(
    bbox: BoundingBox, cache_dir: Path = DEFAULT_CACHE_DIR, extract: Path | None = None
) -> StateGraph:
    """The state graph for `bbox`, from the on-disk cache or freshly built.

    With `extract`, the network and its turn restrictions come from that local
    OSM file and the OSM timestamp from its header. Otherwise they come from
    Overpass: OSMnx keeps its raw responses in `cache_dir/overpass/<bbox key>/`
    and the OSM timestamp is read from them.
    """
    graphml = cache_dir / f"{bbox.cache_key()}.graphml"
    sidecar = graphml.with_suffix(".json")
    restrictions_file = graphml.with_suffix(".restrictions.json")
    if graphml.exists() and sidecar.exists():
        graph = ox.load_graphml(graphml)
        snapshot = json.loads(sidecar.read_text(encoding="utf-8"))
    elif extract is not None:
        xml = cache_dir / "clipped" / f"{bbox.cache_key()}.osm"
        relations = clip_extract(extract, bbox, xml)
        graph = ox.graph_from_xml(xml, retain_all=False)
        ox.save_graphml(graph, graphml)
        restrictions_file.write_text(json.dumps(relations), encoding="utf-8")
        snapshot = asdict(
            NetworkSnapshot(
                bbox=bbox,
                fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
                osm_timestamp=extract_timestamp(extract),
            )
        )
        sidecar.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    else:
        responses_dir = cache_dir / "overpass" / bbox.cache_key()
        responses_dir.mkdir(parents=True, exist_ok=True)
        ox.settings.use_cache = True
        ox.settings.cache_folder = responses_dir
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
                osm_timestamp=_osm_timestamp(responses_dir.glob("*.json")),
            )
        )
        sidecar.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    if not restrictions_file.exists():
        relations = _fetch_restriction_relations(bbox)
        restrictions_file.write_text(json.dumps(relations), encoding="utf-8")
    restrictions, _ = restrictions_from_overpass(
        json.loads(restrictions_file.read_text(encoding="utf-8"))
    )
    return build_state_graph(
        segments_from_osmnx(graph),
        osm_snapshot=snapshot.get("osm_timestamp") or snapshot.get("fetched_at"),
        restrictions=restrictions,
    )


def bbox_around(points: Iterable[LonLat], margin_m: float) -> BoundingBox:
    """The smallest box containing `points`, grown by `margin_m` on every side."""
    lons, lats = zip(*((p.lon, p.lat) for p in points), strict=True)
    dlat = math.degrees(margin_m / EARTH_MEAN_RADIUS_M)
    dlon = dlat / math.cos(math.radians(sum(lats) / len(lats)))
    return BoundingBox(min(lons) - dlon, min(lats) - dlat, max(lons) + dlon, max(lats) + dlat)
