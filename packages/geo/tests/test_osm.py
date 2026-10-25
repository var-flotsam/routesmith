import json

import networkx as nx
import pytest
from shapely import LineString

from starboard.geo import osm
from starboard.geo.osm import (
    BoundingBox,
    fetch_network,
    parse_speed_kph,
    restrictions_from_overpass,
    segments_from_osmnx,
)
from starboard.geo.state_graph import RestrictionKind, TurnRestriction


def osmnx_like_graph() -> nx.MultiDiGraph:
    """Three nodes in a line: a two-way street (both directed edges) and a one-way."""
    graph = nx.MultiDiGraph(crs="epsg:4326")
    graph.add_node(1, x=-73.000, y=41.000)
    graph.add_node(2, x=-72.999, y=41.000)
    graph.add_node(3, x=-72.998, y=41.000)
    bent = LineString([(-73.000, 41.000), (-72.9995, 41.0001), (-72.999, 41.000)])
    common = {"osmid": 100, "name": "Elm Street", "length": 90.0, "maxspeed": "25 mph"}
    graph.add_edge(1, 2, 0, geometry=bent, oneway=False, reversed=False, **common)
    graph.add_edge(
        2, 1, 0, geometry=LineString(bent.coords[::-1]), oneway=False, reversed=True, **common
    )
    graph.add_edge(2, 3, 0, osmid=200, name=["Oak Lane", "Oak Ln"], length=84.0, oneway=True)
    graph.add_node(4, x=-72.997, y=41.000)
    graph.add_edge(3, 4, 0, osmid=300, highway="motorway_link", length=80.0, oneway=True)
    return graph


def test_opposite_edges_become_one_two_way_segment():
    segments = {s.segment_id: s for s in segments_from_osmnx(osmnx_like_graph())}
    assert sorted(segments) == ["1-2-0", "2-3-0", "3-4-0"]

    elm = segments["1-2-0"]
    assert (elm.forward_allowed, elm.reverse_allowed) == (True, True)
    assert len(elm.geometry) == 3
    assert elm.speed_limit_kph == pytest.approx(40.2336)

    oak = segments["2-3-0"]
    assert (oak.forward_allowed, oak.reverse_allowed) == (True, False)
    assert oak.name == "Oak Lane"
    assert len(oak.geometry) == 2
    assert oak.serviceable

    ramp = segments["3-4-0"]
    assert ramp.road_class == "motorway_link"
    assert not ramp.serviceable


@pytest.mark.parametrize(
    ("value", "expected"),
    [("30", 30.0), ("25 mph", 40.2336), ("50 km/h", 50.0), (["25 mph", "30"], 30.0)],
)
def test_parse_speed_kph(value, expected):
    assert parse_speed_kph(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", [None, "signals", "walk", 12, []])
def test_unparseable_speeds_are_none(value):
    assert parse_speed_kph(value) is None


def test_bounding_box_rejects_inverted_corners():
    with pytest.raises(ValueError, match="bounding box"):
        BoundingBox(west=-72.0, south=41.0, east=-73.0, north=42.0)


def test_network_is_fetched_once_then_read_from_cache(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(bbox, **kwargs):
        calls.append(bbox)
        response = {"osm3s": {"timestamp_osm_base": "2026-10-24T09:00:00Z"}, "elements": []}
        (osm.ox.settings.cache_folder / "response.json").write_text(json.dumps(response))
        return osmnx_like_graph()

    def fake_relations(bbox):
        calls.append("relations")
        return {"elements": [relation(1, "no_left_turn", from_way=100, via=2, to_way=200)]}

    monkeypatch.setattr(osm.ox, "graph_from_bbox", fake_fetch)
    monkeypatch.setattr(osm, "_fetch_restriction_relations", fake_relations)
    bbox = BoundingBox(west=-73.001, south=40.999, east=-72.997, north=41.001)

    first = fetch_network(bbox, cache_dir=tmp_path)
    second = fetch_network(bbox, cache_dir=tmp_path)

    assert len(calls) == 2  # one network fetch, one restrictions fetch
    assert [t for t in first.transitions if t.forbidden_by_restriction] == [
        t for t in second.transitions if t.forbidden_by_restriction
    ]
    assert first.osm_snapshot == second.osm_snapshot == "2026-10-24T09:00:00Z"
    assert sorted(first.segments) == sorted(second.segments)
    sidecar = json.loads((tmp_path / f"{bbox.cache_key()}.json").read_text(encoding="utf-8"))
    assert sidecar["osm_timestamp"] == "2026-10-24T09:00:00Z"
    assert sidecar["bbox"]["west"] == -73.001


def relation(rid, value, *, from_way, via, to_way, via_type="node", tag="restriction"):
    return {
        "type": "relation",
        "id": rid,
        "tags": {"type": "restriction", tag: value},
        "members": [
            {"type": "way", "ref": from_way, "role": "from"},
            {"type": via_type, "ref": via, "role": "via"},
            {"type": "way", "ref": to_way, "role": "to"},
        ],
    }


def test_restrictions_are_read_from_overpass_relations():
    body = {
        "elements": [
            relation(1, "no_left_turn", from_way=10, via=5, to_way=11),
            relation(2, "only_straight_on", from_way=12, via=6, to_way=13, tag="restriction:hgv"),
            relation(3, "no_u_turn", from_way=14, via=99, to_way=14, via_type="way"),
            relation(4, "give_way", from_way=15, via=7, to_way=16),
        ]
    }
    restrictions, unsupported = restrictions_from_overpass(body)
    assert restrictions == [
        TurnRestriction(10, 5, 11, RestrictionKind.PROHIBITORY),
        TurnRestriction(12, 6, 13, RestrictionKind.MANDATORY),
    ]
    assert unsupported == 2


def test_segments_keep_their_osm_way_ids():
    segments = {s.segment_id: s for s in segments_from_osmnx(osmnx_like_graph())}
    assert segments["1-2-0"].osm_way_ids == (100,)
