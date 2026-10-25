"""A route as driven: passes, the joins between them, and where each cart was collected.

Both the current route (the baseline) and an optimized route are a
`DrivenRoute`, so one scorecard measures both the same way.
"""

from dataclasses import dataclass

from starboard.solver.graph import Pass, Place, Transition


@dataclass(frozen=True, slots=True)
class Traversal:
    """Driving along one pass from `start_m` to `end_m`, measured in the pass's direction."""

    on_pass: Pass
    start_m: float
    end_m: float
    serviced_stop_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Pickup:
    """One stop collected at `at_m` along `traversals[traversal_index]`."""

    stop_id: str
    traversal_index: int
    at_m: float
    wrong_side: bool


@dataclass(frozen=True, slots=True)
class PlaceVisit:
    """A stop at the yard or a disposal site; `unload` is true at a disposal site."""

    place: Place
    unload: bool


Join = Transition | PlaceVisit


@dataclass(frozen=True, slots=True)
class DrivenRoute:
    """Traversals in driving order; `joins[i]` links traversal i to traversal i + 1.

    A join is a turn from one pass onto the next, or a visit to a place the
    previous pass ends at and the next one starts from. `start` is where the
    route begins, before the first traversal; `closing_visits` happen after
    the last traversal, and `end` is where the route finishes. The current
    route has no start or end place until routes carry a yard.

    `pickups` are in the order the stops were collected. A traversal's
    `serviced_stop_ids` are the stops collected along it. `u_turn_nodes` are
    the nodes where the routing rules allowed a U-turn.
    """

    traversals: tuple[Traversal, ...]
    joins: tuple[Join, ...]
    pickups: tuple[Pickup, ...]
    unreachable_stop_ids: tuple[str, ...]
    u_turn_nodes: frozenset[int] = frozenset()
    start: Place | None = None
    closing_visits: tuple[PlaceVisit, ...] = ()
    end: Place | None = None

    @property
    def transitions(self) -> tuple[Transition, ...]:
        """The turns made, in order."""
        return tuple(j for j in self.joins if isinstance(j, Transition))

    @property
    def place_visits(self) -> tuple[PlaceVisit, ...]:
        """Every visit to a place along the route, in order."""
        return (*(j for j in self.joins if isinstance(j, PlaceVisit)), *self.closing_visits)

    @property
    def wrong_side_stop_ids(self) -> tuple[str, ...]:
        return tuple(p.stop_id for p in self.pickups if p.wrong_side)
