import os
import time

import pytest

from starboard.geo import extract
from starboard.geo.extract import clip_extract, download_extract, is_drivable
from starboard.geo.osm import BoundingBox

SMALL_OSM = """<?xml version="1.0" encoding="UTF-8"?>
<osm version="0.6">
  <node id="1" lon="-73.0000" lat="41.0000"/>
  <node id="2" lon="-72.9990" lat="41.0000"/>
  <node id="3" lon="-72.9980" lat="41.0000"/>
  <node id="4" lon="-72.0000" lat="42.0000"/>
  <node id="5" lon="-72.0010" lat="42.0000"/>
  <way id="10"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way>
  <way id="11"><nd ref="2"/><nd ref="3"/><tag k="highway" v="footway"/></way>
  <way id="12"><nd ref="4"/><nd ref="5"/><tag k="highway" v="residential"/></way>
  <way id="13"><nd ref="2"/><nd ref="3"/><tag k="highway" v="tertiary"/></way>
  <relation id="20">
    <member type="way" ref="10" role="from"/>
    <member type="node" ref="2" role="via"/>
    <member type="way" ref="13" role="to"/>
    <tag k="type" v="restriction"/><tag k="restriction" v="no_right_turn"/>
  </relation>
</osm>
"""


@pytest.mark.parametrize(
    ("tags", "drivable"),
    [
        ({"highway": "residential"}, True),
        ({"highway": "motorway"}, True),
        ({"highway": "footway"}, False),
        ({"highway": "service"}, False),
        ({"highway": "residential", "access": "private"}, False),
        ({"highway": "residential", "motor_vehicle": "no"}, False),
        ({"highway": "tertiary", "area": "yes"}, False),
        ({"name": "Elm Street"}, False),
    ],
)
def test_drive_network_tag_rules(tags, drivable):
    assert is_drivable(tags) is drivable


def test_clip_keeps_drivable_ways_touching_the_box_and_their_restrictions(tmp_path):
    source = tmp_path / "small.osm"
    source.write_text(SMALL_OSM, encoding="utf-8")
    out = tmp_path / "clipped.osm"
    bbox = BoundingBox(west=-73.0005, south=40.9995, east=-72.9985, north=41.0005)

    relations = clip_extract(source, bbox, out)

    clipped = out.read_text(encoding="utf-8")
    assert '<way id="10">' in clipped
    assert '<way id="13">' in clipped  # node 2 is inside, node 3 outside: kept whole
    assert '<way id="11">' not in clipped  # footway
    assert '<way id="12">' not in clipped  # outside the box
    assert '<node id="3"' in clipped
    assert [r["id"] for r in relations["elements"]] == [20]


def test_a_fresh_extract_is_not_downloaded_again(tmp_path, monkeypatch):
    existing = tmp_path / "region-latest.osm.pbf"
    existing.write_bytes(b"cached")

    def no_network(*args, **kwargs):
        raise AssertionError("should not download")

    monkeypatch.setattr(extract.requests, "get", no_network)
    assert download_extract("https://example.org/region-latest.osm.pbf", tmp_path) == existing

    stale = time.time() - 40 * 86_400
    os.utime(existing, (stale, stale))
    with pytest.raises(AssertionError, match="should not download"):
        download_extract("https://example.org/region-latest.osm.pbf", tmp_path)
