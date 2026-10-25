"""Quickest legal connections between passes, and between passes and places.

A connection from pass A to pass B is the quickest way to get from the end of
A to the start of B: the turns made and the passes driven in between, never
against a one-way, never through a restricted turn, and U-turning only at
the nodes the routing rules allow. Places (the yard, a disposal site) are
network nodes; leaving a place means starting any pass that begins there,
and reaching a place means finishing any pass that ends there. Turning
around inside a place is free and is not a street U-turn.

Costs are integer milliseconds, so comparisons are exact and repeatable.
Shortest paths come from SciPy's Dijkstra over the pass graph
(https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csgraph.dijkstra.html).
"""

import itertools
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_array
from scipy.sparse.csgraph import dijkstra

from starboard.solver.costs import drive_seconds, turn_seconds
from starboard.solver.graph import Direction, Pass, StateGraph, Transition

_MS_PER_S = 1000
# Every edge weighs at least this, because the shortest-path routine does not
# distinguish a zero-weight edge from a missing one.
_MIN_EDGE_MS = 1
UNREACHABLE = -1


def allowed_transitions(graph: StateGraph, u_turn_nodes: frozenset[int]) -> list[Transition]:
    """The transitions a truck may take: no restricted turn, U-turns only where allowed."""
    return [
        t
        for t in graph.transitions
        if not t.forbidden_by_restriction and (not t.is_u_turn or t.via_node in u_turn_nodes)
    ]


def traversal_ms(graph: StateGraph, on_pass: Pass) -> int:
    segment = graph.segments[on_pass.segment_id]
    return max(_MIN_EDGE_MS, round(drive_seconds(segment, segment.length_m) * _MS_PER_S))


def turn_ms(transition: Transition) -> int:
    return round(turn_seconds(transition) * _MS_PER_S)


@dataclass(frozen=True, slots=True)
class Place:
    """A network node the route starts, ends or unloads at."""

    name: str
    node: int


class ConnectionCosts:
    """Connections among `anchors` (passes) and `places`, computed once.

    Vertices of the search graph are the graph's passes, then one "leave"
    and one "reach" vertex per place. An edge into pass Y weighs the turn
    onto Y plus driving all of Y, so a path's weight up to B, less B's own
    traversal, is the connection cost to the start of B.
    """

    def __init__(
        self,
        graph: StateGraph,
        u_turn_nodes: frozenset[int],
        anchors: Iterable[Pass],
        places: Iterable[Place] = (),
    ) -> None:
        self._graph = graph
        self._passes: list[Pass] = sorted(
            graph.passes, key=lambda p: (p.segment_id, p.direction.value)
        )
        self._index = {p: i for i, p in enumerate(self._passes)}
        self._places = sorted(set(places), key=lambda p: (p.name, p.node))
        count = len(self._passes)
        self._leave = {place: count + 2 * k for k, place in enumerate(self._places)}
        self._reach = {place: count + 2 * k + 1 for k, place in enumerate(self._places)}
        size = count + 2 * len(self._places)
        self._traversal = np.array([traversal_ms(graph, p) for p in self._passes], dtype=np.int64)

        rows: list[int] = []
        cols: list[int] = []
        weights: list[int] = []
        self._transition: dict[tuple[int, int], Transition] = {}
        for t in allowed_transitions(graph, u_turn_nodes):
            i, j = self._index[t.from_pass], self._index[t.to_pass]
            weight = turn_ms(t) + int(self._traversal[j])
            if (i, j) in self._transition:
                continue  # one transition joins a pair of passes; keep the first
            self._transition[(i, j)] = t
            rows.append(i)
            cols.append(j)
            weights.append(max(_MIN_EDGE_MS, weight))
        starts_at: dict[int, list[int]] = {}
        ends_at: dict[int, list[int]] = {}
        for i, p in enumerate(self._passes):
            segment = graph.segments[p.segment_id]
            start, end = (
                (segment.from_node, segment.to_node)
                if p.direction is Direction.FORWARD
                else (segment.to_node, segment.from_node)
            )
            starts_at.setdefault(start, []).append(i)
            ends_at.setdefault(end, []).append(i)
        for place in self._places:
            for j in starts_at.get(place.node, []):
                rows.append(self._leave[place])
                cols.append(j)
                weights.append(int(self._traversal[j]))
            for i in ends_at.get(place.node, []):
                rows.append(i)
                cols.append(self._reach[place])
                weights.append(_MIN_EDGE_MS)
        matrix = csr_array(
            (np.array(weights, dtype=np.float64), (np.array(rows), np.array(cols))),
            shape=(size, size),
        )

        self._anchors = sorted(set(anchors), key=lambda p: (p.segment_id, p.direction.value))
        sources = [self._index[a] for a in self._anchors] + [
            self._leave[place] for place in self._places
        ]
        self._row = {vertex: k for k, vertex in enumerate(sources)}
        if sources:
            distances, predecessors = dijkstra(
                matrix, directed=True, indices=sources, return_predecessors=True
            )
        else:
            distances = np.zeros((0, size))
            predecessors = np.zeros((0, size), dtype=np.int64)
        self._distances = distances
        self._predecessors = predecessors

    def _vertex_cost(self, source: int, target: int, target_traversal: int) -> int:
        value = self._distances[self._row[source], target]
        if not np.isfinite(value):
            return UNREACHABLE
        return round(float(value)) - target_traversal

    def between(self, a: Pass, b: Pass) -> int:
        """Milliseconds from the end of `a` to the start of `b`, or UNREACHABLE.

        `a` must be an anchor and differ from `b`; a required pass is driven once.
        """
        if a == b:
            raise ValueError("a connection joins two different passes")
        target = self._index[b]
        return self._vertex_cost(self._index[a], target, int(self._traversal[target]))

    def from_place(self, place: Place, b: Pass) -> int:
        """Milliseconds from leaving `place` to the start of `b`, or UNREACHABLE."""
        target = self._index[b]
        return self._vertex_cost(self._leave[place], target, int(self._traversal[target]))

    def to_place(self, a: Pass, place: Place) -> int:
        """Milliseconds from the end of `a` to reaching `place`, or UNREACHABLE."""
        return self._vertex_cost(self._index[a], self._reach[place], _MIN_EDGE_MS)

    def between_places(self, start: Place, end: Place) -> int:
        """Milliseconds from leaving `start` to reaching `end`; 0 for the same node."""
        if start.node == end.node:
            return 0
        return self._vertex_cost(self._leave[start], self._reach[end], _MIN_EDGE_MS)

    def _walk(self, source: int, target: int) -> list[int]:
        row = self._predecessors[self._row[source]]
        vertices = [target]
        while vertices[-1] != source:
            previous = int(row[vertices[-1]])
            if previous < 0:
                raise ValueError("no connection")
            vertices.append(previous)
        return list(reversed(vertices))

    def _passes_on(self, vertices: Sequence[int]) -> list[Pass]:
        return [self._passes[v] for v in vertices if v < len(self._passes)]

    def path_between(self, a: Pass, b: Pass) -> tuple[Transition, ...]:
        """The transitions from the end of `a` to the start of `b`."""
        if a == b:
            raise ValueError("a connection from a pass to itself has no unique path here")
        vertices = self._walk(self._index[a], self._index[b])
        return self._transitions_along(vertices)

    def path_from_place(self, place: Place, b: Pass) -> tuple[Pass, tuple[Transition, ...]]:
        """The first pass driven after leaving `place`, and the transitions to `b`."""
        vertices = self._walk(self._leave[place], self._index[b])[1:]
        return self._passes[vertices[0]], self._transitions_along(vertices)

    def path_to_place(self, a: Pass, place: Place) -> tuple[Transition, ...]:
        """The transitions from the end of `a` until a pass ending at `place` is driven."""
        vertices = self._walk(self._index[a], self._reach[place])[:-1]
        return self._transitions_along(vertices)

    def path_between_places(
        self, start: Place, end: Place
    ) -> tuple[Pass | None, tuple[Transition, ...]]:
        """The first pass and the transitions from leaving `start` to reaching `end`."""
        if start.node == end.node:
            return None, ()
        vertices = self._walk(self._leave[start], self._reach[end])[1:-1]
        return self._passes[vertices[0]], self._transitions_along(vertices)

    def _transitions_along(self, vertices: Sequence[int]) -> tuple[Transition, ...]:
        return tuple(self._transition[pair] for pair in itertools.pairwise(vertices))
