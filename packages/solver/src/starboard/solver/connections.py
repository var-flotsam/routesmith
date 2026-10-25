"""Quickest legal connections between passes, and between passes and places.

A connection from pass A to pass B is the quickest way to get from the end of
A to the start of B: the turns made and the passes driven in between, never
against a one-way, never through a restricted turn, and U-turning only at
the nodes the routing rules allow. Places (the yard, a disposal site) are
network nodes; leaving a place means starting any pass that begins there,
and reaching a place means finishing any pass that ends there. Turning
around inside a place is free and is not a street U-turn, so a connection
may go in and out of the yard or a disposal site to turn round; such a
pass-through is a visit with no unloading.

Costs are integer milliseconds, so comparisons are exact and repeatable.
Shortest paths come from SciPy's Dijkstra over the pass graph
(https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csgraph.dijkstra.html).
"""

import itertools
from collections.abc import Iterable, Sequence

import numpy as np
import numpy.typing as npt
from scipy.sparse import csr_array
from scipy.sparse.csgraph import dijkstra

from starboard.solver.costs import drive_seconds, turn_seconds
from starboard.solver.graph import Direction, Pass, Place, StateGraph, Transition
from starboard.solver.route import Join, PlaceVisit

_MS_PER_S = 1000
# Every edge weighs at least this, because the shortest-path routine does not
# distinguish a zero-weight edge from a missing one.
_MIN_EDGE_MS = 1
UNREACHABLE = -1

# One step of a connection: how the truck gets onto the next pass, and that pass.
Step = tuple[Join, Pass]


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
        self._place_at = {v: place for place, v in self._reach.items()}
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
            # Turning round inside the place: in, then straight out again.
            rows.append(self._reach[place])
            cols.append(self._leave[place])
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

    def between_all(self, passes: Sequence[Pass]) -> npt.NDArray[np.int64]:
        """`between(a, b)` for every ordered pair of `passes` at once, as a matrix.

        Every pass must be an anchor; the diagonal is UNREACHABLE.
        """
        targets = np.array([self._index[p] for p in passes], dtype=np.int64)
        rows = np.array([self._row[self._index[p]] for p in passes], dtype=np.int64)
        block = self._distances[np.ix_(rows, targets)]
        reachable = np.isfinite(block)
        costs = np.rint(np.where(reachable, block, 0.0)).astype(np.int64)
        costs -= self._traversal[targets][None, :]
        costs[~reachable] = UNREACHABLE
        np.fill_diagonal(costs, UNREACHABLE)
        return costs

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

    def path_between(self, a: Pass, b: Pass) -> tuple[Step, ...]:
        """The steps from the end of `a` to the start of `b`, ending with `b`."""
        if a == b:
            raise ValueError("a connection joins two different passes")
        return self._steps(self._walk(self._index[a], self._index[b]))

    def path_from_place(self, place: Place, b: Pass) -> tuple[Pass, tuple[Step, ...]]:
        """The first pass driven after leaving `place`, and the steps from it to `b`."""
        vertices = self._walk(self._leave[place], self._index[b])[1:]
        return self._passes[vertices[0]], self._steps(vertices)

    def path_to_place(self, a: Pass, place: Place) -> tuple[Step, ...]:
        """The steps from the end of `a` until a pass ending at `place` is driven."""
        return self._steps(self._walk(self._index[a], self._reach[place])[:-1])

    def path_between_places(self, start: Place, end: Place) -> tuple[Pass | None, tuple[Step, ...]]:
        """The first pass and the steps from leaving `start` to reaching `end`."""
        if start.node == end.node:
            return None, ()
        vertices = self._walk(self._leave[start], self._reach[end])[1:-1]
        return self._passes[vertices[0]], self._steps(vertices)

    def _steps(self, vertices: Sequence[int]) -> tuple[Step, ...]:
        """Steps along a walk that starts on a pass: a turn, or a pass-through visit."""
        count = len(self._passes)
        steps: list[Step] = []
        visit: PlaceVisit | None = None
        for i, j in itertools.pairwise(vertices):
            if j >= count:
                if j in self._place_at:
                    visit = PlaceVisit(self._place_at[j], unload=False)
                continue
            if i >= count:
                assert visit is not None
                steps.append((visit, self._passes[j]))
                visit = None
            else:
                steps.append((self._transition[(i, j)], self._passes[j]))
        return tuple(steps)
