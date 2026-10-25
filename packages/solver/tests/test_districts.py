"""District partition properties on random grids: exact cover, contiguity, determinism."""

from collections import defaultdict

import pytest
from hypothesis import given
from hypothesis import settings as settings_
from hypothesis import strategies as st

from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid
from starboard.solver.connections import ConnectionCosts
from starboard.solver.districts import partition, unit_costs
from starboard.solver.graph import Place
from starboard.solver.route import RouteSites
from starboard.solver.units import build_units


@st.composite
def areas(draw):
    size = draw(st.integers(3, 6))
    grid = Grid(size=size, one_way_east=frozenset(), one_way_west=frozenset())
    graph = build_state_graph(grid.segments())
    passes = sorted(graph.passes, key=lambda p: (p.segment_id, p.direction.value))
    with_carts = draw(
        st.lists(st.sampled_from(passes), min_size=1, max_size=len(passes), unique=True)
    )
    carts = {p: draw(st.integers(1, 20)) for p in with_carts}
    units = build_units(graph, carts)
    cart_units = sum(1 for u in units.units if not u.is_connector)
    trucks = draw(st.integers(1, min(4, cart_units)))
    sites = RouteSites(Place("yard", 0), Place("disposal", 0))
    connections = ConnectionCosts(graph, frozenset(), list(carts), [sites.yard, sites.disposal])
    return graph, units, trucks, unit_costs(graph, connections, units, sites)


def _connected(units, members: set[str]) -> bool:
    start = min(members)
    seen, stack = {start}, [start]
    while stack:
        for nxt in units.neighbours[stack.pop()]:
            if nxt in members and nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen == members


@given(areas())
@settings_(deadline=None)
def test_every_unit_is_in_exactly_one_district_and_each_district_has_work(area):
    _, units, trucks, costs = area
    result = partition(units, trucks, costs)
    assert set(result.district_of) == {u.unit_id for u in units.units}
    assert set(result.district_of.values()) <= set(range(trucks))
    members = defaultdict(set)
    for u, d in result.district_of.items():
        members[d].add(u)
    for d in range(trucks):
        assert any(not units.by_id[u].is_connector for u in members[d]), d


@given(areas())
@settings_(deadline=None)
def test_districts_are_contiguous_on_a_connected_grid(area):
    _, units, trucks, costs = area
    result = partition(units, trucks, costs)
    for d in range(trucks):
        assert _connected(units, set(result.units_in(d))), d


@given(areas())
@settings_(deadline=None)
def test_the_same_area_gives_the_same_districts(area):
    _, units, trucks, costs = area
    assert partition(units, trucks, costs) == partition(units, trucks, costs)


def test_more_trucks_than_streets_with_carts_is_refused():
    grid = Grid()
    graph = build_state_graph(grid.segments())
    p = graph.passes[0]
    units = build_units(graph, {p: 3})
    sites = RouteSites(Place("yard", 0), Place("disposal", 0))
    connections = ConnectionCosts(graph, frozenset(), [p], [sites.yard, sites.disposal])
    with pytest.raises(ValueError, match="between 1 and 1 trucks"):
        partition(units, 2, unit_costs(graph, connections, units, sites))


def test_two_trucks_split_a_two_sided_area_into_balanced_halves():
    # Carts spread evenly over every street of a 6x6 grid: two districts should carry
    # workloads within the balance margin of each other.
    grid = Grid(size=6, one_way_east=frozenset(), one_way_west=frozenset())
    graph = build_state_graph(grid.segments())
    carts = {p: 5 for p in graph.passes}
    units = build_units(graph, carts)
    sites = RouteSites(Place("yard", 0), Place("disposal", 0))
    connections = ConnectionCosts(graph, frozenset(), list(carts), [sites.yard, sites.disposal])
    costs = unit_costs(graph, connections, units, sites)
    result = partition(units, 2, costs)
    loads = [sum(costs.workload[u] for u in result.units_in(d)) for d in range(2)]
    assert abs(loads[0] - loads[1]) <= 0.2 * (sum(loads) / 2)
