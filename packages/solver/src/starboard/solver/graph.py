"""The street network as the solver sees it: segments, passes and transitions.

A *segment* is one stretch of street between two intersections (or a dead
end). A *pass* is one traversal of one segment in one direction; it exists
only where travel in that direction is legal. A *transition* is a move from
the end of one pass onto the start of another at a shared node, carrying the
heading change the truck makes there. Turn costs and turn rules are applied
to transitions by the solver; this module only describes the network.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class Direction(StrEnum):
    """Travel along a segment's geometry (`forward`) or against it (`reverse`)."""

    FORWARD = "forward"
    REVERSE = "reverse"

    def opposite(self) -> "Direction":
        return Direction.REVERSE if self is Direction.FORWARD else Direction.FORWARD


class CurbSide(StrEnum):
    """Which curb, relative to a direction of travel."""

    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class LonLat:
    lon: float
    lat: float


@dataclass(frozen=True, slots=True)
class StreetSegment:
    """One street segment; `geometry` runs from `from_node` to `to_node`.

    `serviceable` is false for roads with no curbside collection, such as
    motorways and their ramps: the truck may drive them, but no stop is
    placed on them.
    """

    segment_id: str
    from_node: int
    to_node: int
    geometry: tuple[LonLat, ...]
    length_m: float
    name: str | None
    forward_allowed: bool
    reverse_allowed: bool
    speed_limit_kph: float | None = None
    road_class: str | None = None
    serviceable: bool = True
    osm_way_ids: tuple[int, ...] = ()

    @property
    def is_one_way(self) -> bool:
        return self.forward_allowed != self.reverse_allowed


@dataclass(frozen=True, slots=True)
class Pass:
    segment_id: str
    direction: Direction


@dataclass(frozen=True, slots=True)
class Transition:
    """Leaving `from_pass` and entering `to_pass` at `via_node`.

    `heading_change_deg` is in (-180, 180]: positive is a right turn, negative
    a left turn, 0 straight on. A U-turn is a return along the same segment.
    `forbidden_by_restriction` marks a turn a posted restriction prohibits
    (no left turn, only straight on, and so on); the solver never takes it.
    """

    from_pass: Pass
    to_pass: Pass
    via_node: int
    heading_change_deg: float
    is_u_turn: bool
    forbidden_by_restriction: bool = False


@dataclass(frozen=True, slots=True)
class StateGraph:
    """Every legal pass and every transition between passes.

    `dead_end_nodes` are nodes touched by a single segment, where a U-turn is
    always allowed; a node where the network was cut off at the edge of the
    fetched area is not one. `osm_snapshot` records the OSM data timestamp the network
    was built from, or `None` for synthetic networks.
    """

    segments: Mapping[str, StreetSegment]
    passes: tuple[Pass, ...]
    transitions: tuple[Transition, ...]
    dead_end_nodes: frozenset[int]
    osm_snapshot: str | None = None


@dataclass(frozen=True, slots=True)
class SnappedStop:
    """A stop placed on a segment.

    `distance_along_m` is measured from the segment's `from_node`.
    `side_of_forward` is the curb the stop is on when travelling the segment
    forward; `required_pass` is the pass that has it on the truck's right.
    `street` is the street named in the stop's address, when it has one.
    """

    stop_id: str
    segment_id: str
    distance_along_m: float
    distance_from_centerline_m: float
    side_of_forward: CurbSide
    required_pass: Pass
    street: str | None = None


@dataclass(frozen=True, slots=True)
class Place:
    """A network node a route starts, ends or unloads at, such as the yard or a disposal site."""

    name: str
    node: int
