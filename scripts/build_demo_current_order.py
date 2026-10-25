"""Give the demo stops a realistic current order: a well-drawn rear-loader route.

The demo's buyer still runs routes drawn for rear-loaders, whose crews collect
both curbs in one pass. This script draws such a route for the demo stops and
writes its order into data/demo/stops.csv as `current_sequence`, keeping the
street-and-house-number order as `alphabetical_sequence`.

Each street with carts is driven once, in the direction that has more of its
carts on the right (the only legal direction on a one-way), and the solver
orders those passes from the yard to the disposal site and back. Run from the
repository root, with the Connecticut extract cached (see data/demo/PROVENANCE.md):

    uv run python scripts/build_demo_current_order.py
"""

import csv
import json
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from starboard.cli.stop_file import read_stop_file
from starboard.geo.osm import bbox_around, fetch_network
from starboard.geo.places import place_at
from starboard.geo.snapping import snap_stops
from starboard.solver.graph import LonLat, Pass
from starboard.solver.optimize import SolveSettings, optimize
from starboard.solver.route import RouteSites, TruckProfile

STOPS = Path("data/demo/stops.csv")
ROUTE = Path("data/demo/route.json")
EXTRACT = Path("cache/osm/extracts/connecticut-latest.osm.pbf")
NETWORK_MARGIN_M = 300.0  # as the CLI uses


def main() -> None:
    config = json.loads(ROUTE.read_text(encoding="utf-8"))
    yard = LonLat(lon=config["yard"]["lon"], lat=config["yard"]["lat"])
    disposal = LonLat(lon=config["disposal"]["lon"], lat=config["disposal"]["lat"])
    stop_file = read_stop_file(STOPS)
    points = [s.location for s in stop_file.stops] + [yard, disposal]
    graph = fetch_network(bbox_around(points, NETWORK_MARGIN_M), extract=EXTRACT)
    sites = RouteSites(place_at(graph, "yard", yard), place_at(graph, "disposal", disposal))
    snapped = snap_stops(graph, stop_file.stops).snapped

    # A rear-loader collects both curbs: one pass per street, in its majority direction.
    votes: dict[str, Counter[Pass]] = defaultdict(Counter)
    legal = set(graph.passes)
    for stop in snapped:
        if stop.required_pass in legal:
            votes[stop.segment_id][stop.required_pass] += 1
    chosen = {seg: count.most_common(1)[0][0] for seg, count in votes.items()}
    both_curbs = [
        replace(s, required_pass=chosen[s.segment_id]) for s in snapped if s.segment_id in chosen
    ]

    profile = TruckProfile(capacity_carts=config.get("capacity_carts"))
    result = optimize(graph, both_curbs, sites, SolveSettings(profile))
    order = {p.stop_id: k for k, p in enumerate(result.route.pickups, start=1)}

    with STOPS.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    alphabetical = {
        r["stop_id"]: r.get("alphabetical_sequence") or r["current_sequence"] for r in rows
    }
    last = len(order)
    unplaced = sorted(
        (r for r in rows if r["stop_id"] not in order),
        key=lambda r: int(alphabetical[r["stop_id"]]),
    )
    for r in unplaced:  # stops in review keep their place at the end, in street order
        last += 1
        order[r["stop_id"]] = last
    rows.sort(key=lambda r: order[r["stop_id"]])
    fields = [
        "stop_id",
        "current_sequence",
        "alphabetical_sequence",
        "house_number",
        "street",
        "lon",
        "lat",
    ]
    with STOPS.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    **{k: r[k] for k in ("stop_id", "house_number", "street", "lon", "lat")},
                    "current_sequence": order[r["stop_id"]],
                    "alphabetical_sequence": alphabetical[r["stop_id"]],
                }
            )
    print(f"ordered {len(result.route.pickups)} stops; {len(unplaced)} in review placed last")


if __name__ == "__main__":
    main()
