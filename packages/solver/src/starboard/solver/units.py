"""Street units: the pieces an area is split into when it is shared by several trucks.

A unit is a stretch of one street with every required pass on it, so both
curbs of a street always go to the same truck (ADR-0003). Consecutive
segments of the same street that meet at a node no other segment touches
form one unit; segments with carts and segments without are never mixed.
A unit with no carts is a connector: it carries no work, but it keeps
districts joined along the streets between them.

Two units are adjacent when they share a node. The distance between two
units is the quickest legal connection from one to the other, in either
order, over any of their passes, as the U-distance of Mourão et al. (2009,
https://ciencia.iscte-iul.pt/publications/heuristic-methods-for-the-sectoring-arc-routing-problem/10316)
applied to directed passes.
"""

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

from starboard.solver import defaults
from starboard.solver.connections import UNREACHABLE, ConnectionCosts, traversal_ms
from starboard.solver.graph import Pass, StateGraph

_MS_PER_S = 1000


@dataclass(frozen=True, slots=True)
class StreetUnit:
    """`required_passes` carry `carts` in all; a connector has none of either."""

    unit_id: str
    segment_ids: tuple[str, ...]
    nodes: frozenset[int]
    required_passes: tuple[Pass, ...]
    carts: int

    @property
    def is_connector(self) -> bool:
        return not self.required_passes


@dataclass(frozen=True, slots=True)
class UnitGraph:
    """The units of an area, in id order, and which units share a node with which."""

    units: tuple[StreetUnit, ...]
    neighbours: Mapping[str, tuple[str, ...]]
    by_id: Mapping[str, StreetUnit]


def build_units(graph: StateGraph, carts_on: Mapping[Pass, int]) -> UnitGraph:
    """Every serviceable segment in exactly one unit; `carts_on` gives each required pass."""
    segments = {
        sid: s for sid, s in sorted(graph.segments.items()) if s.serviceable or _has(carts_on, sid)
    }
    touching: dict[int, list[str]] = defaultdict(list)
    for sid, s in segments.items():
        touching[s.from_node].append(sid)
        if s.to_node != s.from_node:
            touching[s.to_node].append(sid)

    def with_carts(sid: str) -> bool:
        return _has(carts_on, sid)

    def joins(a: str, b: str) -> bool:
        first, second = segments[a], segments[b]
        return (
            first.name is not None and first.name == second.name and with_carts(a) == with_carts(b)
        )

    # Union segments across nodes exactly two of them touch, when they belong together.
    parent = {sid: sid for sid in segments}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for node in sorted(touching):
        pair = touching[node]
        if len(pair) == 2 and pair[0] != pair[1] and joins(pair[0], pair[1]):
            a, b = sorted((find(pair[0]), find(pair[1])))
            parent[b] = a

    groups: dict[str, list[str]] = defaultdict(list)
    for sid in segments:
        groups[find(sid)].append(sid)
    units: list[StreetUnit] = []
    unit_of: dict[str, str] = {}
    for root in sorted(groups):
        members = tuple(sorted(groups[root]))
        passes = tuple(
            sorted(
                (p for p in carts_on if p.segment_id in members),
                key=lambda p: (p.segment_id, p.direction.value),
            )
        )
        nodes = frozenset(
            n for sid in members for n in (segments[sid].from_node, segments[sid].to_node)
        )
        unit = StreetUnit(
            f"u:{members[0]}", members, nodes, passes, sum(carts_on[p] for p in passes)
        )
        units.append(unit)
        for sid in members:
            unit_of[sid] = unit.unit_id

    neighbours: dict[str, set[str]] = defaultdict(set)
    for sids in touching.values():
        ids = {unit_of[sid] for sid in sids}
        for u in ids:
            neighbours[u] |= ids - {u}
    return UnitGraph(
        tuple(units),
        {u.unit_id: tuple(sorted(neighbours[u.unit_id])) for u in units},
        {u.unit_id: u for u in units},
    )


def _has(carts_on: Mapping[Pass, int], segment_id: str) -> bool:
    return any(p.segment_id == segment_id and n > 0 for p, n in carts_on.items())


def unit_distance_ms(
    connections: ConnectionCosts, graph: StateGraph, a: StreetUnit, b: StreetUnit
) -> int:
    """Quickest legal connection between two units in either order, or UNREACHABLE.

    The passes of `a` (and of `b`, for the other order) must be anchors of
    `connections`. Connectors are reached over every legal pass on their segments.
    """
    best = UNREACHABLE
    for first, second in ((a, b), (b, a)):
        if not first.required_passes:
            continue
        for p in first.required_passes:
            for q in _passes_of(graph, second):
                if p == q:
                    return 0
                cost = connections.between(p, q)
                if cost != UNREACHABLE and (best == UNREACHABLE or cost < best):
                    best = cost
    return best


def _passes_of(graph: StateGraph, unit: StreetUnit) -> list[Pass]:
    if unit.required_passes:
        return list(unit.required_passes)
    members = set(unit.segment_ids)
    return [p for p in graph.passes if p.segment_id in members]


def workload_ms(graph: StateGraph, unit: StreetUnit) -> int:
    """Estimated route time a unit adds: servicing its passes and carts, plus expected dead-head."""
    cart_ms = round(defaults.CART_SERVICE_TIME.value * _MS_PER_S)
    driving = sum(traversal_ms(graph, p) for p in unit.required_passes)
    dead_head = round(driving * defaults.DEAD_HEAD_ESTIMATE_FACTOR.value)
    return driving + dead_head + unit.carts * cart_ms
