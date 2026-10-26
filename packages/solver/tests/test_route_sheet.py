"""Route sheets: one step per street and turn, unloads on their own, carts in order."""

from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.graph import Direction, Pass, Place
from starboard.solver.route import DrivenRoute, PlaceVisit, Traversal
from starboard.solver.route_sheet import Action, route_sheet

GRID = Grid(one_way_east=frozenset(), one_way_west=frozenset())
GRAPH = build_state_graph(GRID.segments())
DISPOSAL = Place("disposal", 0)


def _turn(a: Pass, b: Pass):
    return next(t for t in GRAPH.transitions if t.from_pass == a and t.to_pass == b)


def _route(passes, stops=None, visit_after=None):
    stops = stops or {}
    traversals = tuple(
        Traversal(p, 0.0, GRAPH.segments[p.segment_id].length_m, tuple(stops.get(k, ())))
        for k, p in enumerate(passes)
    )
    joins = []
    for k in range(len(passes) - 1):
        if k == visit_after:
            joins.append(PlaceVisit(DISPOSAL, unload=True))
        else:
            joins.append(_turn(passes[k], passes[k + 1]))
    return DrivenRoute(traversals, tuple(joins), (), (), frozenset())


EAST_0 = Pass("h-0-0", Direction.FORWARD)
EAST_1 = Pass("h-0-1", Direction.FORWARD)
NORTH = Pass("v-0-2", Direction.FORWARD)


def test_a_street_driven_straight_on_is_one_step():
    steps = route_sheet(GRAPH, _route([EAST_0, EAST_1], {0: ["a"], 1: ["b", "c"]}))
    assert [(s.action, s.street, s.distance_m, s.stop_ids) for s in steps] == [
        (Action.DEPART, "Row 0 Street", 200.0, ("a", "b", "c")),
        (Action.ARRIVE, None, 0.0, ()),
    ]


def test_a_turn_starts_a_new_step_on_the_new_street():
    steps = route_sheet(GRAPH, _route([EAST_0, EAST_1, NORTH]))
    assert [(s.action, s.street) for s in steps] == [
        (Action.DEPART, "Row 0 Street"),
        (Action.LEFT, "Column 2 Avenue"),
        (Action.ARRIVE, None),
    ]


def test_an_unload_is_a_step_of_its_own():
    steps = route_sheet(GRAPH, _route([EAST_0, EAST_1], visit_after=0))
    assert [s.action for s in steps] == [
        Action.DEPART,
        Action.UNLOAD,
        Action.DEPART,
        Action.ARRIVE,
    ]
