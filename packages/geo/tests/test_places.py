import pytest

from starboard.geo.places import place_at
from starboard.geo.state_graph import build_state_graph
from starboard.geo.synthetic import Grid

GRID = Grid()
GRAPH = build_state_graph(GRID.segments())


def test_a_site_takes_the_nearest_node():
    place = place_at(GRAPH, "yard", GRID.at(190.0, 120.0))
    assert place.node == GRID.node(1, 2)
    assert place.name == "yard"


def test_a_site_far_from_every_street_is_refused():
    with pytest.raises(ValueError, match="not within"):
        place_at(GRAPH, "yard", GRID.at(-5000.0, -5000.0))
