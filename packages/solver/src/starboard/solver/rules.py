"""Where a truck may turn around.

U-turns are always allowed at dead ends, where there is no other way out.
Elsewhere the routing rules choose one of three policies. Under the default,
`low-density`, a U-turn at an intersection is allowed only where every
street meeting there is a quiet road class and is itself sparse: its stops,
counted over the street or over `defaults.U_TURN_DENSITY_WINDOW` if the
street is shorter, stay below `defaults.U_TURN_MAX_STOP_DENSITY`. So turning
around does not happen on busy roads or next to a tightly packed block.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from starboard.solver import defaults
from starboard.solver.graph import SnappedStop, StateGraph, StreetSegment

# Road classes where this product allows turning a truck around in low-density
# areas: residential and living streets, service roads, and unclassified minor
# roads, which carry the sparse rural frontage low-density U-turns are for. This
# is a stated default, not a classification OSM makes; class definitions are at
# https://wiki.openstreetmap.org/wiki/Key:highway
QUIET_ROAD_CLASSES = frozenset({"residential", "unclassified", "living_street", "service"})

_METRES_PER_KM = 1000.0


class UTurnPolicy(StrEnum):
    DEAD_ENDS_ONLY = "dead-ends-only"
    LOW_DENSITY = "low-density"
    ANYWHERE = "anywhere"


@dataclass(frozen=True, slots=True)
class RoutingRules:
    """Rules for driving between stops; the baseline and the solver both follow them."""

    u_turns: UTurnPolicy = UTurnPolicy.LOW_DENSITY


def u_turn_nodes(
    graph: StateGraph, stops: Iterable[SnappedStop], rules: RoutingRules
) -> frozenset[int]:
    """Every node where a U-turn is allowed under `rules`, dead ends included."""
    if rules.u_turns is UTurnPolicy.DEAD_ENDS_ONLY:
        return graph.dead_end_nodes
    nodes_touched: dict[int, list[str]] = defaultdict(list)
    for segment in graph.segments.values():
        nodes_touched[segment.from_node].append(segment.segment_id)
        if segment.to_node != segment.from_node:
            nodes_touched[segment.to_node].append(segment.segment_id)
    if rules.u_turns is UTurnPolicy.ANYWHERE:
        return frozenset(nodes_touched)

    stops_on: dict[str, int] = defaultdict(int)
    for stop in stops:
        stops_on[stop.segment_id] += 1

    def sparse(segment: StreetSegment) -> bool:
        window_km = max(segment.length_m, defaults.U_TURN_DENSITY_WINDOW.value) / _METRES_PER_KM
        return stops_on[segment.segment_id] / window_km < defaults.U_TURN_MAX_STOP_DENSITY.value

    allowed = set(graph.dead_end_nodes)
    for node, segment_ids in nodes_touched.items():
        segments = [graph.segments[s] for s in segment_ids]
        if all(s.road_class in QUIET_ROAD_CLASSES and sparse(s) for s in segments):
            allowed.add(node)
    return frozenset(allowed)
