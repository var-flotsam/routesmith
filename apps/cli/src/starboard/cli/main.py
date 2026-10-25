"""`starboard score <stops.csv>`: the scorecard for the current route, no solve."""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

import requests

from starboard.cli.stop_file import read_stop_file
from starboard.geo.osm import DEFAULT_CACHE_DIR, bbox_around, fetch_network
from starboard.geo.snapping import snap_stops
from starboard.solver.baseline import RoutingRules, build_baseline
from starboard.solver.scorecard import Scorecard, score

# Room around the outermost stops for the streets that bound them.
NETWORK_MARGIN_M = 300.0

_ROWS = (
    ("Distance", "distance_m", "{:,.0f} m"),
    ("Drive time", "drive_time_s", "{:,.0f} s"),
    ("Left turns", "left_turns", "{:,}"),
    ("Right turns", "right_turns", "{:,}"),
    ("U-turns", "u_turns", "{:,}"),
    ("Wrong-side pickups", "wrong_side_pickups", "{:,}"),
    ("Dead-head distance", "dead_head_m", "{:,.0f} m"),
    ("Street passes", "street_passes", "{:,}"),
    ("Stops serviced", "stops_serviced", "{:,}"),
    ("Stops unreachable", "stops_unreachable", "{:,}"),
)


def _table(card: Scorecard) -> str:
    values = asdict(card)
    width = max(len(label) for label, _, _ in _ROWS)
    return "\n".join(f"{label:<{width}}  {fmt.format(values[key])}" for label, key, fmt in _ROWS)


def score_command(args: argparse.Namespace) -> int:
    stop_file = read_stop_file(args.stops)
    if not stop_file.stops:
        print(f"no readable stops in {args.stops}", file=sys.stderr)
        for row in stop_file.rejected:
            print(f"  line {row.line_number}: {row.reason}", file=sys.stderr)
        return 1

    bbox = bbox_around((s.location for s in stop_file.stops), NETWORK_MARGIN_M)
    try:
        graph = fetch_network(bbox, cache_dir=args.cache_dir)
    except requests.RequestException as error:
        print(f"could not fetch the OSM street network: {error}", file=sys.stderr)
        return 2
    outcome = snap_stops(graph, stop_file.stops)
    route = build_baseline(
        graph, outcome.snapped, RoutingRules(u_turns_at_intersections=args.allow_u_turns)
    )
    card = score(graph, route)
    review = Counter(item.reason.value for item in outcome.review)

    if args.json:
        report = {
            "scorecard": asdict(card),
            "osm_snapshot": graph.osm_snapshot,
            "rejected_rows": len(stop_file.rejected),
            "review_items": dict(sorted(review.items())),
        }
        print(json.dumps(report, indent=2))
        return 0

    print(f"Current route: {args.stops}")
    print(f"OSM snapshot: {graph.osm_snapshot}")
    print()
    print(_table(card))
    print()
    print(f"Rows rejected: {len(stop_file.rejected)}")
    print(f"Stops in review: {len(outcome.review)}")
    for reason, count in sorted(review.items()):
        print(f"  {reason}: {count}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starboard", description="Starboard Routing")
    commands = parser.add_subparsers(dest="command", required=True)
    score_parser = commands.add_parser("score", help="scorecard for the current route, no solve")
    score_parser.add_argument("stops", type=Path, help="stop CSV, as in data/demo/stops.csv")
    score_parser.add_argument("--json", action="store_true", help="print the report as JSON")
    score_parser.add_argument(
        "--allow-u-turns", action="store_true", help="allow U-turns at intersections"
    )
    score_parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    score_parser.set_defaults(handler=score_command)
    args = parser.parse_args(argv)
    result: int = args.handler(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
