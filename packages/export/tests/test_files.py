"""CSV, GPX and KML exports, compared byte for byte with snapshots in tests/snapshots/.

Run with UPDATE_SNAPSHOTS=1 to write new snapshots after an intended change.
"""

import importlib.util
import os
from pathlib import Path

import pytest

from starboard.export.files import routes_gpx, routes_kml, stops_csv

SNAPSHOTS = Path(__file__).parent / "snapshots"


def _sample():
    spec = importlib.util.spec_from_file_location("sample", Path(__file__).parent / "sample.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RUN


@pytest.mark.parametrize(
    ("make", "name"),
    [(stops_csv, "stops.csv"), (routes_gpx, "routes.gpx"), (routes_kml, "routes.kml")],
)
def test_the_export_matches_its_snapshot_byte_for_byte(make, name):
    data = make(_sample())
    snapshot = SNAPSHOTS / name
    if os.environ.get("UPDATE_SNAPSHOTS") == "1":
        snapshot.write_bytes(data)
    assert data == snapshot.read_bytes()
    assert make(_sample()) == data  # the same run, the same bytes


def test_the_csv_lists_stops_in_each_routes_collection_order():
    rows = stops_csv(_sample()).decode().splitlines()
    assert rows[0] == "route,sequence,stop_id,street,lon,lat,current_route,current_sequence"
    assert [r.split(",")[:3] for r in rows[1:]] == [
        ["1", "1", "s2"],
        ["1", "2", "s1"],
        ["2", "1", "s3"],
        ["2", "2", "s9"],
    ]


def test_names_are_escaped_in_xml():
    gpx = routes_gpx(_sample()).decode()
    assert "Byram &amp; Mill, route 1" in gpx
    assert "<" not in gpx.split("<name>")[1].split("</name>")[0]
