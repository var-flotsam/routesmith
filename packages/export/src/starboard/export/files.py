"""CSV of stops in the new order, and GPX and KML of each route's path.

A route's path follows OpenStreetMap's streets, so the GPX and KML files credit
OpenStreetMap and its licence, as the Open Database Licence asks of produced works
(ODbL 1.0, section 4.3). The CSV holds the upload's own stops and needs no credit.

Every file is built from text alone: fixed column order, coordinates to six decimal
places (about 0.1 m), `\\n` line endings, and no timestamps, so one run always gives
byte-identical files (CLAUDE.md, exports are deterministic).
"""

import csv
import io
from xml.sax.saxutils import escape

from starboard.export.model import RunExport

OSM_COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/"

CSV_COLUMNS = (
    "route",
    "sequence",
    "stop_id",
    "street",
    "lon",
    "lat",
    "current_route",
    "current_sequence",
)


def _coordinate(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


def stops_csv(run: RunExport) -> bytes:
    """One row per served stop, in each route's collection order, routes numbered from 1."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for route_number, route in enumerate(run.routes, start=1):
        for sequence, stop_id in enumerate(route.order, start=1):
            stop = run.stops.get(stop_id)
            writer.writerow(
                [
                    route_number,
                    sequence,
                    stop_id,
                    "" if stop is None or stop.street is None else stop.street,
                    _coordinate(None if stop is None else stop.lon),
                    _coordinate(None if stop is None else stop.lat),
                    "" if stop is None or stop.current_route is None else stop.current_route,
                    "" if stop is None else stop.current_sequence,
                ]
            )
    return buffer.getvalue().encode("utf-8")


def osm_credit(run: RunExport) -> str:
    """The OpenStreetMap credit every file with a route's path carries, with the data's date."""
    return (
        "Streets © OpenStreetMap contributors, under the Open Database Licence "
        f"(openstreetmap.org/copyright), as of {run.osm_snapshot or 'a date not recorded'}."
    )


def _name(run: RunExport, route_number: int) -> str:
    return escape(f"{run.route_name}, route {route_number}")


def routes_gpx(run: RunExport) -> bytes:
    """A GPX 1.1 track per route (https://www.topografix.com/GPX/1/1/)."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="Starboard Routing" xmlns="http://www.topografix.com/GPX/1/1">',
        "  <metadata>",
        f"    <name>{escape(run.route_name)}</name>",
        f"    <desc>{escape(osm_credit(run))}</desc>",
        '    <copyright author="OpenStreetMap contributors">',
        f"      <license>{ODBL_URL}</license>",
        "    </copyright>",
        f'    <link href="{OSM_COPYRIGHT_URL}"><text>OpenStreetMap copyright</text></link>',
        "  </metadata>",
    ]
    for route_number, route in enumerate(run.routes, start=1):
        lines.append(f"  <trk><name>{_name(run, route_number)}</name><trkseg>")
        lines.extend(
            f'    <trkpt lat="{_coordinate(lat)}" lon="{_coordinate(lon)}"/>'
            for lon, lat in route.path
        )
        lines.append("  </trkseg></trk>")
    lines.append("</gpx>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def routes_kml(run: RunExport) -> bytes:
    """A KML 2.2 line per route (https://developers.google.com/kml/documentation/kmlreference)."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        f"  <Document><name>{escape(run.route_name)}</name>",
        f"    <description>{escape(osm_credit(run))}</description>",
    ]
    for route_number, route in enumerate(run.routes, start=1):
        coordinates = " ".join(f"{_coordinate(lon)},{_coordinate(lat)}" for lon, lat in route.path)
        lines.extend(
            [
                f"    <Placemark><name>{_name(run, route_number)}</name>",
                f"      <LineString><coordinates>{coordinates}</coordinates></LineString>",
                "    </Placemark>",
            ]
        )
    lines.extend(["  </Document>", "</kml>"])
    return ("\n".join(lines) + "\n").encode("utf-8")
