"""The starboard command line.

`starboard score <stops.csv>` prints the current route's scorecard, no solve.
`starboard optimize <stops.csv> --route route.json` also solves the optimized
route and prints both scorecards side by side. The route file gives the yard,
the disposal site and the truck (see data/demo/route.json); `--yard`,
`--disposal`, `--capacity` and `--max-hours` override it. Write sites with
"=" (`--yard=-73.65,41.02`), since a negative longitude reads as a flag.

When the stop file has a `route_id` column, each truck's current route is
driven on its own and the area's current scorecard is the sum of them;
`optimize` then splits the area among as many trucks as there are current
routes unless `--trucks` says otherwise.
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
from starboard.solver.baseline import build_baseline, current_routes, routes_by_id
from starboard.solver.fleet import Area, FleetSettings, solve_routes
from starboard.solver.graph import LonLat, StateGraph
from starboard.solver.objectives import RouteObjective
from starboard.solver.optimize import SolveSettings, optimize
from starboard.solver.route import RouteSites, TruckProfile
from starboard.solver.rules import RoutingRules, UTurnPolicy
from starboard.solver.scorecard import Scorecard, area_scorecard, score

# Room around the outermost stops and sites for the streets that bound them.
NETWORK_MARGIN_M = 300.0
_SECONDS_PER_HOUR = 3600.0
_MS_PER_S = 1000

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


def _columns(headers: Sequence[str], cards: Sequence[Scorecard]) -> str:
    """One column per scorecard, under its header."""
    width = max(len(label) for label, _, _ in _ROWS)
    lines = [f"{'':<{width}}" + "".join(f"  {h:>12}" for h in headers)]
    for label, key, fmt in _ROWS:
        values = [fmt.format(asdict(c)[key]) for c in cards]
        lines.append(f"{label:<{width}}" + "".join(f"  {v:>12}" for v in values))
    return "\n".join(lines)


def _extract_path(value: str | None, cache_dir: Path) -> Path | None:
    """A local extract path as given, or a URL downloaded into the cache."""
    if value is None:
        return None
    if value.startswith(("https://", "http://")):
        return download_extract(value, cache_dir / "extracts")
    return Path(value)


def _apply_route_file(args: argparse.Namespace) -> None:
    """Fill sites and truck from `--route`, leaving any value given on the command line."""
    if args.route is None:
        return
    config = json.loads(args.route.read_text(encoding="utf-8"))
    for key in ("yard", "disposal"):
        if getattr(args, key) is None and key in config:
            setattr(args, key, LonLat(lon=float(config[key]["lon"]), lat=float(config[key]["lat"])))
    if args.capacity is None and config.get("capacity_carts") is not None:
        args.capacity = int(config["capacity_carts"])
    if args.max_hours is None and config.get("max_route_hours") is not None:
        args.max_hours = float(config["max_route_hours"])


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
    _apply_route_file(args)
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
    stops, route_of = loaded.outcome.snapped, loaded.stop_file.route_of
    if route_of:
        routes = current_routes(
            loaded.graph, routes_by_id(stops, route_of), rules, loaded.sites, _profile(args)
        )
        by_route = {route_id: score(loaded.graph, r) for route_id, r in routes.items()}
        card = area_scorecard(list(by_route.values()))
    else:
        route = build_baseline(
            loaded.graph, stops, rules, sites=loaded.sites, profile=_profile(args)
        )
        by_route, card = {}, score(loaded.graph, route)
    review = Counter(item.reason.value for item in loaded.outcome.review)
    if args.json:
        report = {
            "scorecard": asdict(card),
            "routes": {route_id: asdict(c) for route_id, c in by_route.items()},
            "osm_snapshot": loaded.graph.osm_snapshot,
            "rejected_rows": len(loaded.stop_file.rejected),
            "review_items": dict(sorted(review.items())),
        }
        print(json.dumps(report, indent=2))
        return 0
    print(f"Current route: {args.stops}")
    print(f"OSM snapshot: {loaded.graph.osm_snapshot}")
    print()
    if by_route:
        print(_columns([*by_route, "Area"], [*by_route.values(), card]))
    else:
        print(_table(card))
    _print_footer(loaded)
    return 0


def optimize_command(args: argparse.Namespace) -> int:
    _apply_route_file(args)
    if args.yard is None or args.disposal is None:
        print(
            "optimize needs a yard and a disposal site: --route, or --yard and --disposal",
            file=sys.stderr,
        )
        return 1
    loaded = _load(args)
    if isinstance(loaded, int):
        return loaded
    assert loaded.sites is not None
    rules = RoutingRules(u_turns=UTurnPolicy(args.u_turns))
    profile = _profile(args)
    stops = loaded.outcome.snapped
    route_of = loaded.stop_file.route_of
    if args.trucks is None:
        args.trucks = len(set(route_of.values())) or 1
    if args.trucks > 1 or route_of:
        return _optimize_fleet(args, loaded, SolveSettings(profile, rules))
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
            "time_limited": result.time_limited,
        }
        print(json.dumps(report, indent=2))
        return 0
    print(f"Route: {args.stops}")
    print(f"OSM snapshot: {loaded.graph.osm_snapshot}")
    print()
    print(_comparison(now, new))
    if result.time_limited:
        print("\nThe search hit its time ceiling; this route may differ on another machine")
    if result.over_duration_s > 0:
        print(f"\nOptimized route is {result.over_duration_s:,.0f} s over the maximum duration")
    if unserved:
        print("\nStops the optimized route cannot serve:")
        for reason, count in sorted(unserved.items()):
            print(f"  {reason}: {count}")
    _print_footer(loaded)
    return 0


def _optimize_fleet(args: argparse.Namespace, loaded: _Loaded, settings: SolveSettings) -> int:
    """Several routes: one district per truck, each with its own scorecard."""
    assert loaded.sites is not None
    area = Area(loaded.graph, tuple(loaded.outcome.snapped), loaded.sites)
    fleet = FleetSettings(args.trucks, RouteObjective(args.objective), settings)
    try:
        result = solve_routes(area, fleet, warm_start=loaded.outcome.snapped)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    cards = [score(loaded.graph, r.route) for r in result.routes]
    route_of = loaded.stop_file.route_of
    current: dict[str, Scorecard] = {}
    if route_of:
        driven = current_routes(
            loaded.graph,
            routes_by_id(area.stops, route_of),
            settings.rules,
            area.sites,
            settings.profile,
        )
        current = {route_id: score(loaded.graph, r) for route_id, r in driven.items()}
    summary = {
        "objective": result.objective.value,
        "total_route_time_s": result.total_ms / _MS_PER_S,
        "longest_route_time_s": result.longest_ms / _MS_PER_S,
        "total_lower_bound_s": result.total_bound_ms / _MS_PER_S,
        "gap": result.gap,
        "balance_met": result.balance_met,
        "unserved": dict(sorted(Counter(u.reason.value for u in result.unserved).items())),
    }
    if args.json:
        report = {
            "routes": [asdict(c) for c in cards],
            "area": summary,
            "optimized_area": asdict(area_scorecard(cards)),
            "osm_snapshot": loaded.graph.osm_snapshot,
        }
        if current:
            report["current_routes"] = {route_id: asdict(c) for route_id, c in current.items()}
            report["current_area"] = asdict(area_scorecard(list(current.values())))
        print(json.dumps(report, indent=2))
        return 0
    print(f"Area: {args.stops}, {args.trucks} trucks, objective {result.objective.value}")
    print(f"OSM snapshot: {loaded.graph.osm_snapshot}")
    if current:
        print()
        print(f"Current routes ({len(current)})")
        print(_columns(list(current), list(current.values())))
    print()
    print(f"Optimized routes ({len(cards)})")
    print(_columns([f"Route {k + 1}" for k in range(len(cards))], cards))
    if current:
        print()
        print("Area")
        print(_comparison(area_scorecard(list(current.values())), area_scorecard(cards)))
    print()
    total, longest = result.total_ms / _MS_PER_S, result.longest_ms / _MS_PER_S
    bound = result.total_bound_ms / _MS_PER_S
    print(f"Total route time {total:,.0f} s, longest {longest:,.0f} s")
    print(f"Best found; at most {result.gap:.1%} above the lower bound of {bound:,.0f} s")
    print("Routes within the balance margin" if result.balance_met else "Balance margin not met")
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
    parser.add_argument(
        "--route", type=Path, metavar="FILE", help="route file: yard, disposal site, truck"
    )
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
    optimize_parser.add_argument(
        "--trucks",
        type=int,
        metavar="N",
        help="split the area into N routes (default: the number of current routes, else 1)",
    )
    optimize_parser.add_argument(
        "--objective",
        choices=[o.value for o in RouteObjective],
        default=RouteObjective.BALANCED_TOTAL.value,
        help="what best means for several routes (default: %(default)s)",
    )
    optimize_parser.set_defaults(handler=optimize_command)
    args = parser.parse_args(argv)
    result: int = args.handler(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
