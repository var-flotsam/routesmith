"""Split an area's street units into N contiguous, compact districts of similar workload.

District first, route second (ADR-0003): each district is later routed by the
single-route solver. Here the units are only assigned.

1. Seeds: N units with carts, chosen by farthest-first traversal on unit
   distance, starting from the unit farthest from the yard
   (https://en.wikipedia.org/wiki/Farthest-first_traversal).
2. Balanced growth: the open district with the least estimated workload takes
   the unassigned unit that touches it and is closest to its seed (Cortinhal
   et al. 2015, https://ciencias.ulisboa.pt/sites/default/files/fcul/unidinvestig/cio/1.2015.pdf).
   Units no district can reach along the streets start a new piece of the
   district with the least workload, nearest its seed.
3. Re-centring: each seed moves to its district's medoid and the districts
   grow again, `defaults.PARTITION_RECENTRING_ROUNDS` times.
4. Refinement: a boundary unit moves to a neighbouring district while that
   lowers the score (workload outside the balance margin, cuts between
   residential units, and spread around each district's medoid), never
   splitting the district it leaves and never leaving it without carts.

Everything is deterministic: ties break on unit ids and district indices.
"""

import heapq
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from starboard.solver import defaults
from starboard.solver.connections import UNREACHABLE, ConnectionCosts
from starboard.solver.graph import StateGraph
from starboard.solver.route import RouteSites
from starboard.solver.units import StreetUnit, UnitGraph, unit_distance_ms, workload_ms

_MS_PER_S = 1000
UNREACHABLE_DISTANCE = 10**12

# Road classes along which a district boundary costs nothing: busy roads drivers
# and planners read as edges on a map. https://wiki.openstreetmap.org/wiki/Key:highway
ARTERIAL_ROAD_CLASSES = frozenset(
    {
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
    }
)

Distance = Callable[[str, str], int]


@dataclass(frozen=True, slots=True)
class Partition:
    """`district_of[unit_id]` is the district, 0 to N - 1, each unit belongs to."""

    district_of: Mapping[str, int]
    trucks: int

    def units_in(self, district: int) -> list[str]:
        return sorted(u for u, d in self.district_of.items() if d == district)


class _Area:
    def __init__(
        self,
        units: UnitGraph,
        distance: Distance,
        workload: Mapping[str, int],
        road_class: Mapping[str, str | None],
    ) -> None:
        self.units = units
        self.ids = [u.unit_id for u in units.units]
        self.carts = {u.unit_id for u in units.units if not u.is_connector}
        self.workload = workload
        self.road_class = road_class
        self._distance = distance
        self._cache: dict[tuple[str, str], int] = {}

    def distance(self, a: str, b: str) -> int:
        if a == b:
            return 0
        key = (a, b) if a < b else (b, a)
        if key not in self._cache:
            value = self._distance(a, b)
            self._cache[key] = UNREACHABLE_DISTANCE if value < 0 else value
        return self._cache[key]

    def components(self, members: set[str]) -> int:
        return pieces(self.units, members)


def pieces(units: UnitGraph, members: set[str]) -> int:
    """How many pieces, connected along the streets, a set of units falls into."""
    seen: set[str] = set()
    count = 0
    for start in sorted(members):
        if start in seen:
            continue
        count += 1
        stack = [start]
        seen.add(start)
        while stack:
            for nxt in units.neighbours[stack.pop()]:
                if nxt in members and nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
    return count


def _seeds(area: _Area, trucks: int, from_yard: Mapping[str, int]) -> list[str]:
    carts = sorted(area.carts)
    first = max(carts, key=lambda u: (from_yard.get(u, 0), _neg(u)))
    seeds = [first]
    while len(seeds) < trucks:
        best = max(
            (u for u in carts if u not in seeds),
            key=lambda u: (min(area.distance(u, s) for s in seeds), _neg(u)),
        )
        seeds.append(best)
    return seeds


def _neg(unit_id: str) -> tuple[int, ...]:
    """Sort key that makes the lowest id win a `max`."""
    return tuple(-ord(c) for c in unit_id)


def _grow(area: _Area, seeds: Sequence[str]) -> dict[str, int]:
    """Balanced growth from the seeds over the unit graph."""
    district_of: dict[str, int] = {s: d for d, s in enumerate(seeds)}
    load = [area.workload.get(s, 0) for s in seeds]
    frontier: list[list[tuple[int, str]]] = [[] for _ in seeds]

    def offer(d: int, unit: str) -> None:
        for nxt in area.units.neighbours[unit]:
            if nxt not in district_of:
                heapq.heappush(frontier[d], (area.distance(seeds[d], nxt), nxt))

    for d, s in enumerate(seeds):
        offer(d, s)
    remaining = set(area.ids) - set(district_of)
    while remaining:
        open_districts = [d for d in range(len(seeds)) if frontier[d]]
        if not open_districts:
            # Units no district reaches along the streets: the lightest district
            # takes the one nearest its seed, and grows a new piece from it.
            d = min(range(len(seeds)), key=lambda k: (load[k], k))
            unit = min(remaining, key=lambda u: (area.distance(seeds[d], u), u))
        else:
            d = min(open_districts, key=lambda k: (load[k], k))
            _, unit = heapq.heappop(frontier[d])
            if unit in district_of:
                continue
        district_of[unit] = d
        load[d] += area.workload.get(unit, 0)
        remaining.discard(unit)
        offer(d, unit)
    return district_of


def _medoid(area: _Area, members: Sequence[str]) -> str:
    candidates = [u for u in members if u in area.carts] or list(members)
    return min(candidates, key=lambda u: (sum(area.distance(u, v) for v in candidates), u))


class _Score:
    """The refinement score in ms: balance excess, boundary cuts, and spread."""

    def __init__(self, area: _Area, trucks: int) -> None:
        self.area = area
        self.trucks = trucks
        self.cut_ms = round(defaults.BOUNDARY_CUT_COST.value * _MS_PER_S)
        self.spread_weight = defaults.COMPACTNESS_WEIGHT.value
        self.margin = defaults.BALANCE_MARGIN.value

    def cut_counts(self, a: str, b: str) -> bool:
        units = self.area.units.by_id
        if units[a].is_connector or units[b].is_connector:
            return False
        return not (
            self.area.road_class.get(a) in ARTERIAL_ROAD_CLASSES
            or self.area.road_class.get(b) in ARTERIAL_ROAD_CLASSES
        )

    def __call__(self, district_of: Mapping[str, int]) -> int:
        area = self.area
        loads = [0] * self.trucks
        members: dict[int, list[str]] = defaultdict(list)
        for u, d in district_of.items():
            loads[d] += area.workload.get(u, 0)
            members[d].append(u)
        mean = sum(loads) / self.trucks
        balance = sum(max(0.0, abs(w - mean) - self.margin * mean) for w in loads)
        cuts = sum(
            1
            for u in area.ids
            for v in area.units.neighbours[u]
            if u < v and district_of[u] != district_of[v] and self.cut_counts(u, v)
        )
        spread = 0
        for units in members.values():
            centre = _medoid(area, sorted(units))
            spread += sum(
                min(area.distance(centre, u), _SPREAD_CAP_MS) for u in units if u in area.carts
            )
        return round(balance + cuts * self.cut_ms + self.spread_weight * spread)


# A unit unreachable from its medoid adds this much spread, not an overflow.
_SPREAD_CAP_MS = 10**9


def _refine(area: _Area, district_of: dict[str, int], trucks: int) -> dict[str, int]:
    score = _Score(area, trucks)
    current = score(district_of)
    for _ in range(round(defaults.PARTITION_REFINEMENT_PASSES.value)):
        improved = False
        for unit in area.ids:
            here = district_of[unit]
            targets = sorted({district_of[n] for n in area.units.neighbours[unit]} - {here})
            for there in targets:
                donor = {u for u, d in district_of.items() if d == here}
                rest = donor - {unit}
                if not rest or not (rest & area.carts):
                    continue
                if area.components(rest) > area.components(donor):
                    continue
                district_of[unit] = there
                trial = score(district_of)
                if trial < current:
                    current, improved = trial, True
                    break
                district_of[unit] = here
        if not improved:
            break
    return district_of


@dataclass(frozen=True, slots=True)
class UnitCosts:
    """What the partition knows about units.

    `distance(a, b)` is the unit distance in ms (negative when unreachable),
    `workload` each unit's estimated route time, `from_yard` each cart unit's
    distance from the yard, and `road_class` each unit's OSM road class.
    """

    distance: Distance
    workload: Mapping[str, int]
    from_yard: Mapping[str, int]
    road_class: Mapping[str, str | None]


def partition(units: UnitGraph, trucks: int, costs: UnitCosts) -> Partition:
    """Assign every unit to one of `trucks` districts.

    Raises ValueError unless 1 <= trucks <= the number of units with carts.
    """
    area = _Area(units, costs.distance, costs.workload, costs.road_class)
    if not 1 <= trucks <= len(area.carts):
        raise ValueError(f"need between 1 and {len(area.carts)} trucks, got {trucks}")
    seeds = _seeds(area, trucks, costs.from_yard)
    district_of = _grow(area, seeds)
    for _ in range(round(defaults.PARTITION_RECENTRING_ROUNDS.value)):
        members: dict[int, list[str]] = defaultdict(list)
        for u, d in district_of.items():
            members[d].append(u)
        recentred = [_medoid(area, sorted(members[d])) for d in range(trucks)]
        if recentred == seeds:
            break
        seeds = recentred
        district_of = _grow(area, seeds)
    return Partition(_refine(area, district_of, trucks), trucks)


def road_classes(
    units: Sequence[StreetUnit], segment_class: Mapping[str, str | None]
) -> dict[str, str | None]:
    """Each unit's road class, taken from its first segment."""
    return {u.unit_id: segment_class.get(u.segment_ids[0]) for u in units}


def unit_costs(
    graph: StateGraph, connections: ConnectionCosts, units: UnitGraph, sites: RouteSites
) -> UnitCosts:
    """Unit distances, workloads, yard distances and road classes for an area.

    The required passes of every unit, and both sites, must be in `connections`.
    """

    def distance(a: str, b: str) -> int:
        return unit_distance_ms(connections, graph, units.by_id[a], units.by_id[b])

    from_yard = {}
    for unit in units.units:
        legs = [connections.from_place(sites.yard, p) for p in unit.required_passes]
        reachable = [leg for leg in legs if leg != UNREACHABLE]
        if reachable:
            from_yard[unit.unit_id] = min(reachable)
    return UnitCosts(
        distance,
        {u.unit_id: workload_ms(graph, u) for u in units.units},
        from_yard,
        {u.unit_id: graph.segments[u.segment_ids[0]].road_class for u in units.units},
    )
