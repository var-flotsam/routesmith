"""The starboard command line.

`starboard score <stops.csv>` prints the current route's scorecard, no solve.
`starboard optimize <stops.csv> --yard=LON,LAT --disposal=LON,LAT` also solves
the optimized route and prints both scorecards side by side. Write the sites
with "=", since a negative longitude would otherwise read as a flag.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import requests

from starboard.cli.stop_file import StopFile, read_stop_file
from starboard.geo.extract import download_extract
from starboard.geo.osm import DEFAULT_CACHE_DIR, bbox_around, fetch_network
from starboard.geo.places import place_at
from starboard.geo.snapping import SnapOutcome, snap_stops
from starboard.solver.baseline import build_baseline
from starboard.solver.graph import LonLat, StateGraph
from starboard.solver.optimize import SolveSettings, optimize
from starboard.solver.route import RouteSites, TruckProfile
from starboard.solver.rules import RoutingRules, UTurnPolicy
from starboard.solver.scorecard import Scorecard, score

# Room around the outermost stops and sites for the streets that bound them.
NETWORK_MARGIN_M = 300.0
_SECONDS_PER_HOUR = 3600.0

_ROWS = (
    ("Distance", "distance_m", "{:,.0f} m"),
    ("Route time", "route_time_s", "{:,.0f} s"),
    ("  driving", "drive_time_s", "{:,.0f} s"),
    ("  collecting carts", "service_time_s", "{:,.0f} s"),
    ("  wrong-side extra", "wrong_side_time_s", "{:,.0f} s"),
    ("  unloading", "unload_time_s", "{:,.0f} s"),
    ("Left turns", "left_turns", "{:,}"),
    ("Right turns", "right_turns", "{:,}"),
    ("U-turns", "u_turns", "{:,}"),
    ("Wrong-side pickups", "wrong_side_pickups", "{:,}"),
    ("Dead-head distance", "dead_head_m", "{:,.0f} m"),
    ("Street passes", "street_passes", "{:,}"),
    ("Disposal visits", "disposal_visits", "{:,}"),
    ("Stops serviced", "stops_serviced", "{:,}"),
    ("Stops unreachable", "stops_unreachable", "{:,}"),
)


def _table(card: Scorecard) -> str:
    values = asdict(card)
    width = max(len(label) for label, _, _ in _ROWS)
    return "\n".join(f"{label:<{width}}  {fmt.format(values[key])}" for label, key, fmt in _ROWS)


def _comparison(current: Scorecard, optimized: Scorecard) -> str:
    now, new = asdict(current), asdict(optimized)
    width = max(len(label) for label, _, _ in _ROWS)
    lines = [f"{'':<{width}}  {'Current':>14}  {'Optimized':>14}  {'Change':>14}"]
    for label, key, fmt in _ROWS:
        change = new[key] - now[key]
        sign = "+" if change > 0 else ""
        lines.append(
            f"{label:<{width}}  {fmt.format(now[key]):>14}  {fmt.format(new[key]):>14}"
            f"  {sign + fmt.format(change):>14}"
        )
    return "\n".join(lines)


def _extract_path(value: str | None, cache_dir: Path) -> Path | None:
    """A local extract path as given, or a URL downloaded into the cache."""
    if value is None:
        return None
    if value.startswith(("https://", "http://")):
        return download_extract(value, cache_dir / "extracts")
    return Path(value)


def _lon_lat(text: str) -> LonLat:
    try:
        lon, lat = (float(part) for part in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError("expected LON,LAT, for example -73.65,41.00") from None
    return LonLat(lon=lon, lat=lat)


@dataclass(frozen=True, slots=True)
class _Loaded:
    stop_file: StopFile
    graph: StateGraph
    outcome: SnapOutcome
    sites: RouteSites | None


def _load(args: argparse.Namespace) -> _Loaded | int:
    """Read the stops, fetch the network and snap; an exit code on failure."""
    stop_file = read_stop_file(args.stops)
    if not stop_file.stops:
        print(f"no readable stops in {args.stops}", file=sys.stderr)
        for row in stop_file.rejected:
            print(f"  line {row.line_number}: {row.reason}", file=sys.stderr)
        return 1
    points = [s.location for s in stop_file.stops]
    points += [p for p in (args.yard, args.disposal) if p is not None]
    bbox = bbox_around(points, NETWORK_MARGIN_M)
    try:
        extract = _extract_path(args.osm_extract, args.cache_dir)
        graph = fetch_network(bbox, cache_dir=args.cache_dir, extract=extract)
    except requests.RequestException as error:
        print(f"could not fetch the OSM street network: {error}", file=sys.stderr)
        return 2
    sites = None
    if args.yard is not None and args.disposal is not None:
        try:
            sites = RouteSites(
                place_at(graph, "yard", args.yard), place_at(graph, "disposal", args.disposal)
            )
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
    elif args.yard is not None or args.disposal is not None:
        print("give both --yard and --disposal, or neither", file=sys.stderr)
        return 1
    return _Loaded(stop_file, graph, snap_stops(graph, stop_file.stops), sites)


def _profile(args: argparse.Namespace) -> TruckProfile:
    hours = args.max_hours
    return TruckProfile(
        capacity_carts=args.capacity,
        max_route_duration_s=None if hours is None else hours * _SECONDS_PER_HOUR,
    )


def _print_footer(loaded: _Loaded) -> None:
    review = Counter(item.reason.value for item in loaded.outcome.review)
    print()
    print(f"Rows rejected: {len(loaded.stop_file.rejected)}")
    print(f"Stops in review: {len(loaded.outcome.review)}")
    for reason, count in sorted(review.items()):
        print(f"  {reason}: {count}")


def score_command(args: argparse.Namespace) -> int:
    loaded = _load(args)
    if isinstance(loaded, int):
        return loaded
    rules = RoutingRules(u_turns=UTurnPolicy(args.u_turns))
    route = build_baseline(
        loaded.graph, loaded.outcome.snapped, rules, sites=loaded.sites, profile=_profile(args)
    )
    card = score(loaded.graph, route)
    review = Counter(item.reason.value for item in loaded.outcome.review)
    if args.json:
        report = {
            "scorecard": asdict(card),
            "osm_snapshot": loaded.graph.osm_snapshot,
            "rejected_rows": len(loaded.stop_file.rejected),
            "review_items": dict(sorted(review.items())),
        }
        print(json.dumps(report, indent=2))
        return 0
    print(f"Current route: {args.stops}")
    print(f"OSM snapshot: {loaded.graph.osm_snapshot}")
    print()
    print(_table(card))
    _print_footer(loaded)
    return 0


def optimize_command(args: argparse.Namespace) -> int:
    if args.yard is None or args.disposal is None:
        print("optimize needs --yard and --disposal", file=sys.stderr)
        return 1
    loaded = _load(args)
    if isinstance(loaded, int):
        return loaded
    assert loaded.sites is not None
    rules = RoutingRules(u_turns=UTurnPolicy(args.u_turns))
    profile = _profile(args)
    stops = loaded.outcome.snapped
    try:
        current = build_baseline(loaded.graph, stops, rules, sites=loaded.sites, profile=profile)
        result = optimize(
            loaded.graph, stops, loaded.sites, SolveSettings(profile, rules), warm_start=stops
        )
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    now, new = score(loaded.graph, current), score(loaded.graph, result.route)
    unserved = Counter(u.reason.value for u in result.unserved)
    if args.json:
        report = {
            "current": asdict(now),
            "optimized": asdict(new),
            "osm_snapshot": loaded.graph.osm_snapshot,
            "optimized_order": [p.stop_id for p in result.route.pickups],
            "unserved": dict(sorted(unserved.items())),
            "over_duration_s": result.over_duration_s,
        }
        print(json.dumps(report, indent=2))
        return 0
    print(f"Route: {args.stops}")
    print(f"OSM snapshot: {loaded.graph.osm_snapshot}")
    print()
    print(_comparison(now, new))
    if result.over_duration_s > 0:
        print(f"\nOptimized route is {result.over_duration_s:,.0f} s over the maximum duration")
    if unserved:
        print("\nStops the optimized route cannot serve:")
        for reason, count in sorted(unserved.items()):
            print(f"  {reason}: {count}")
    _print_footer(loaded)
    return 0


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("stops", type=Path, help="stop CSV, as in data/demo/stops.csv")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument(
        "--u-turns",
        choices=[policy.value for policy in UTurnPolicy],
        default=UTurnPolicy.LOW_DENSITY.value,
        help="where U-turns are allowed besides dead ends (default: %(default)s)",
    )
    parser.add_argument(
        "--yard", type=_lon_lat, metavar="LON,LAT", help="where routes start and end"
    )
    parser.add_argument("--disposal", type=_lon_lat, metavar="LON,LAT", help="where trucks unload")
    parser.add_argument("--capacity", type=int, metavar="CARTS", help="carts per load")
    parser.add_argument("--max-hours", type=float, metavar="HOURS", help="maximum route duration")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument(
        "--osm-extract",
        metavar="PATH_OR_URL",
        help="build the network from an OSM extract (.osm.pbf) instead of Overpass",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="starboard", description="Starboard Routing")
    commands = parser.add_subparsers(dest="command", required=True)
    score_parser = commands.add_parser("score", help="scorecard for the current route, no solve")
    _common(score_parser)
    score_parser.set_defaults(handler=score_command)
    optimize_parser = commands.add_parser(
        "optimize", help="solve the optimized route and compare it with the current one"
    )
    _common(optimize_parser)
    optimize_parser.set_defaults(handler=optimize_command)
    args = parser.parse_args(argv)
    result: int = args.handler(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
