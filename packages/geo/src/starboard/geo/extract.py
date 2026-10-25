"""Street networks from a downloaded OSM extract, such as a Geofabrik region file.

An extract is the alternative to Overpass: one file per region, read
locally, refreshed when it is older than `defaults.OSM_EXTRACT_MAX_AGE`.
Only drivable ways that touch the bounding box are kept, using the same
tag rules as OSMnx's "drive" network
(https://github.com/gboeing/osmnx/blob/main/osmnx/_overpass.py), so a
network built from an extract matches one fetched from Overpass.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any  # restriction bodies mirror Overpass's untyped JSON
from xml.sax.saxutils import quoteattr

import osmium
import requests

from starboard.solver import defaults

if TYPE_CHECKING:
    from starboard.geo.osm import BoundingBox

GEOFABRIK_CONNECTICUT = "https://download.geofabrik.de/north-america/us/connecticut-latest.osm.pbf"
_SECONDS_PER_DAY = 86_400
_DOWNLOAD_CHUNK_BYTES = 1 << 20

# Tag values that take a way out of the drive network; a way is excluded when
# its tag matches the pattern anywhere, as in an Overpass `!~` filter.
_EXCLUDED = {
    "area": re.compile("yes"),
    "access": re.compile("private"),
    "highway": re.compile(
        "abandoned|bridleway|bus_guideway|construction|corridor|cycleway|elevator|escalator|"
        "footway|no|path|pedestrian|planned|platform|proposed|raceway|razed|rest_area|service|"
        "services|steps|track"
    ),
    "motor_vehicle": re.compile("no"),
    "motorcar": re.compile("no"),
    "service": re.compile("alley|driveway|emergency_access|parking|parking_aisle|private"),
}


def is_drivable(tags: dict[str, str]) -> bool:
    if "highway" not in tags:
        return False
    return not any(key in tags and pattern.search(tags[key]) for key, pattern in _EXCLUDED.items())


def download_extract(url: str, directory: Path) -> Path:
    """The extract at `url`, downloaded into `directory` unless a fresh copy is there."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / url.rsplit("/", 1)[-1]
    max_age_s = defaults.OSM_EXTRACT_MAX_AGE.value * _SECONDS_PER_DAY
    if target.exists() and time.time() - target.stat().st_mtime < max_age_s:
        return target
    partial = target.with_suffix(target.suffix + ".partial")
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with partial.open("wb") as handle:
            for chunk in response.iter_content(_DOWNLOAD_CHUNK_BYTES):
                handle.write(chunk)
    partial.replace(target)
    return target


def extract_timestamp(pbf: Path) -> str | None:
    """The OSM data timestamp the extract's header records, if any."""
    reader = osmium.io.Reader(str(pbf), osmium.osm.osm_entity_bits.NOTHING)
    try:
        value = reader.header().get("osmosis_replication_timestamp")
    finally:
        reader.close()
    return value or None


def _inside(bbox: BoundingBox, lon: float, lat: float) -> bool:
    return bbox.west <= lon <= bbox.east and bbox.south <= lat <= bbox.north


def _xml_tags(tags: dict[str, str]) -> Iterable[str]:
    for key, value in sorted(tags.items()):
        yield f"    <tag k={quoteattr(key)} v={quoteattr(value)}/>"


def clip_extract(pbf: Path, bbox: BoundingBox, out_xml: Path) -> dict[str, Any]:
    """Write the drivable ways touching `bbox` to `out_xml` as OSM XML.

    Returns the restriction relations among those ways, in the shape of an
    Overpass `out body` response, for `restrictions_from_overpass`.
    """
    nodes: dict[int, tuple[float, float]] = {}
    ways: dict[int, tuple[list[int], dict[str, str]]] = {}
    processor = (
        osmium.FileProcessor(str(pbf), osmium.osm.NODE | osmium.osm.WAY)
        .with_locations()
        .with_filter(osmium.filter.KeyFilter("highway"))
    )
    for way in processor:
        if not isinstance(way, osmium.osm.Way):
            continue
        tags = {tag.k: tag.v for tag in way.tags}
        if not is_drivable(tags):
            continue
        points = [(n.ref, n.location.lon, n.location.lat) for n in way.nodes if n.location.valid()]
        if len(points) != len(way.nodes) or not any(_inside(bbox, x, y) for _, x, y in points):
            continue
        ways[way.id] = ([ref for ref, _, _ in points], tags)
        nodes.update({ref: (x, y) for ref, x, y in points})

    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<osm version="0.6">']
    lines += [
        f'  <node id="{ref}" lon="{x:.7f}" lat="{y:.7f}"/>' for ref, (x, y) in sorted(nodes.items())
    ]
    for way_id, (refs, tags) in sorted(ways.items()):
        lines.append(f'  <way id="{way_id}">')
        lines += [f'    <nd ref="{ref}"/>' for ref in refs]
        lines += _xml_tags(tags)
        lines.append("  </way>")
    lines.append("</osm>")
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    out_xml.write_text("\n".join(lines) + "\n", encoding="utf-8")

    relations: list[dict[str, Any]] = []
    restrictions = osmium.FileProcessor(str(pbf), osmium.osm.RELATION).with_filter(
        osmium.filter.TagFilter(("type", "restriction"))
    )
    for relation in restrictions:
        if not isinstance(relation, osmium.osm.Relation):
            continue
        members = [
            {
                "type": {"n": "node", "w": "way", "r": "relation"}[m.type],
                "ref": m.ref,
                "role": m.role,
            }
            for m in relation.members
        ]
        if not any(m["type"] == "way" and m["ref"] in ways for m in members):
            continue
        relations.append(
            {
                "type": "relation",
                "id": relation.id,
                "tags": {tag.k: tag.v for tag in relation.tags},
                "members": members,
            }
        )
    return {"elements": relations}
