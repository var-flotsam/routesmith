# ADR-0003: Multiple routes: districts first, then the single-route solver

Date: 2026-10-25

## Context

The owner asks for the option to break an area into multiple routes: the tool
takes a number of trucks N and returns the best solution it can find for that
many routes. Chosen defaults: exactly N routes, all trucks share one truck
profile, one yard and one disposal site, and every stop is served by exactly
one truck. HANDOFF.md §1 listed districting as out of scope; this ADR records
the scope change, and HANDOFF.md §1, §4 and §6 change with it.

**Objective (decided by the owner, 2026-10-25).** Least total route time, with
every route kept within a balance margin of the average route time, so no
driver ends up with the overtime. The two other candidates, least longest
route and least total only, stay available as options.

**Scale.** One route is 600 to 1,200 stops and solves in under three minutes
(HANDOFF §2.1). An area splits into up to about 10 routes, so a run can hold
about 10,000 stops. On the demo town, 692 snapped stops fall on 183 required
passes (about 3.8 stops per pass) on 107 serviced segments; at that ratio a
10,000-stop area has about 2,600 required passes and one route 160 to 320.

**Why not one model over the whole area.** The single-route model (HANDOFF
§2.3) is a directed rural postman problem with turn penalties (Benavent &
Soler 1999), solved by turning required arcs into nodes for OR-Tools routing.
Extending it to N vehicles over every required pass is direct, but published
results show one search at that size is slow: up to 60 minutes for 833
services (Vidal 2017), and hours for thousands of tasks (Tang et al. 2017),
where decomposition gives better results in much less time on large instances
(Mei et al. 2014). One model is also one search, which a worker cannot spread
across processes, and it only softly encourages districts a driver can learn.

Three designs were compared, each scored by three independent judges (driver
and hauler, operations research, shipping engineer):

- **One N-vehicle model over every required pass.** Joint assignment and
  sequencing, objectives map onto OR-Tools span costs; unproven at 2,600+
  nodes and weak on district shape.
- **Route first, cluster second** (Beasley 1983). One giant tour, then an
  exact-N split (Vidal 2016), with disposal visits placed as in Willemse &
  Joubert (2016); the giant tour needs the single-route solver at ten times its
  size, and cuts can give the two curbs of a street to different trucks.
- **District first, route second** (Butsch et al. 2014; Muyldermans et al.
  2003). Two of the three judges chose it.

## Decision

An area is split into N routes district first, route second:

1. Partition the area's streets into N contiguous, compact districts balanced
   by estimated workload.
2. Route each district with the single-route solver on the full network.
3. Exchange street units between neighbouring districts, priced on real route
   times, until no move improves the objective.

Districting decides only which required passes each route serves; it never
restricts which passes or turns a route may drive. With N = 1 the district
layer is skipped and the run is exactly the single-route solver.

**Street units.** A unit is one serviced segment with all its required passes,
so both curbs of a street always go to one truck. Consecutive segments of one
street joined at a node no other segment touches merge into one unit.
Unserviced segments are connector units with no carts, so contiguity follows
the streets. Unit distance is the quickest legal, turn-aware time between two
units in either order (the U-distance of Mourão et al. 2009, as used by
Cortinhal et al. 2015).

**Partition.** Seeds are chosen by farthest-first traversal on unit distance;
when the upload names each stop's current route and exactly N routes, the
current routes are the start instead, so optimized districts stay recognisable.
Districts grow in balance: the district with the least estimated workload takes
the nearest unassigned unit that touches it (Cortinhal et al. 2015). Boundary
refinement in the Kernighan-Lin / Fiduccia-Mattheyses style (Karypis & Kumar
1998) then moves boundary units, never letting a district split into more
pieces. A small cost per cut between adjacent residential units pulls
boundaries onto arterial roads, where drivers and planners can read them.

**Routing each district.** Each district's required passes are solved by the
single-route solver, with connection costs from the full network, so a route
may dead-head through a neighbour. It collects only its own district's carts.
The allowed U-turn set is computed once from all of the area's stops and passed
to every solve, so low-density U-turns are judged on the whole street, not on
one district's share of it.

**Exchange.** Relocate a boundary unit, or swap two boundary units, on
granular candidate lists of each unit's nearest units in the other district.
A move is priced by splicing, re-optimised by the single-route local search on
the two changed routes, and kept only if the objective improves on the
re-solved times. The changed districts are then solved again with OR-Tools,
and the route set with the better acceptance key is kept, so the exchange
never makes a result worse. Moves keep the partition's district rules (no
district split into more pieces, none left without carts). 2-opt* tail
exchange (Vidal 2017) is not used: a route's tail cuts across street units,
so it would split streets and districts. Later PRs add a two-vehicle
OR-Tools re-solve of adjacent pairs and an optional giant-tour split restart.

**Objective.** Route time t_k is drive time with turn costs (yard and disposal
legs included), cart service time and disposal unload time. Candidates are
compared lexicographically in integer milliseconds:

- **balanced total (default):** first the time over any maximum route duration
  the truck profile sets, then the total time outside the balance margin
  (Σ max(0, |t_k − t̄| − m·t̄)), then the total time Σ t_k;
- **longest route:** duration excess, then max t_k, then the total;
- **total:** duration excess, then the total; refused without a maximum route
  duration, since it otherwise drifts to one long route and N − 1 token ones.

A result that misses the margin or the duration cap is returned flagged, with
its largest deviation. Every result reports a lower bound on the total and the
gap to it, and the UI says "best found", never "optimal": the min-max
k-Chinese postman problem is NP-hard (Ahr & Reinelt 2006).

**Hard constraints.** Invariants 1 to 4 hold for every route, because every
route is expanded by the single-route solver on the full network with the same
rules. A new invariant 5: exactly N routes, each serving at least one stop,
every serviceable stop served by exactly one route, all starting and ending at
the shared yard and using the shared disposal site. An independent pure-Python
checker re-validates every returned route set; a failure fails the run. The
existing property tests keep every assertion; a new fleet strategy adds N, a
yard, a disposal site and a capacity, and checks invariant 5, N = 1 equivalence
and determinism.

**Determinism.** Inputs sort canonically; ties break on ids; nothing order-
dependent iterates a set of strings. The run seed drives Starboard's own
randomised steps through local `random.Random` instances, and each district's
seed derives from the run seed and its index. OR-Tools routing exposes no seed,
so its searches stop on solution counts, not wall time. A test solves the same
input twice, and again under a different `PYTHONHASHSEED`, and compares the
results byte for byte.

**Scale.** District solves run through a `map` function the caller passes in
(the worker passes a process pool's), so the solver itself stays pure. Wall time
is about ⌈N / P⌉ district solves plus the exchange loop, for P processes; a
benchmark at 1,000, 3,000 and 10,000 stops sets the search budgets.

### New tunables (`packages/solver/defaults.py`)

| Name | Default | Reason |
| --- | --- | --- |
| `BALANCE_MARGIN` | 0.10 | Each route within 10% of the average route time: about 45 minutes on a 7.5-hour shift. Confirmed by the owner, 2026-10-25. |
| `MULTI_ROUTE_TIME_LIMIT_PER_ROUTE` | 180 s | Wall-clock safety ceiling per route, matching the single-route target; budgets counted in work normally stop the run first. |
| `BOUNDARY_CUT_COST` | 30 s per cut | Charged per pair of adjacent residential units in different districts, so boundaries fall on arterial roads. |
| `COMPACTNESS_WEIGHT` | 0.1 | Weight on summed unit-to-centre time, so districts are compact rather than long and thin. |
| `DISPOSAL_UNLOAD_TIME` | pending | Time at the disposal site per visit; needs a public figure before it is set. |
| Search budgets | set by benchmark | First-solve share, exchange sweeps, candidate list length, re-centring rounds. |

Every value is a stated default with its reason except where a public source
is given in `defaults.py`.

### Delivery

PRs in order, each one concern with its tests. Steps 1 to 4 need no OR-Tools
and can land while the single-route solver is built; steps 5 onward need it.

1. Connection costs: a shared allowed-transition rule and an all-pairs
   pass-to-pass cost table in integer milliseconds (`scipy`, BSD-3-Clause),
   tested against the baseline router.
2. Street units, the unit graph, unit distances and the workload estimate.
3. Route objectives: the three acceptance keys, lower bounds and gap,
   `BALANCE_MARGIN`.
4. District partition and refinement, with property tests for exact cover,
   contiguity, N non-empty districts and determinism.
5. Route sets: the fleet types, the independent checker and invariant 5 (added
   to CLAUDE.md).
6. `solve_routes()`: district solves, route numbering, per-route scorecards,
   fleet property tests.
7. Benchmark at 1,000 to 10,000 stops (`pytest -m benchmark`, outside the merge
   gate), setting the search budgets.
8. The exchange loop.
9. Current routes per truck from an optional route-id column, and the area
   scorecard.
10. `starboard optimize --trucks N [--objective ...] [--balance-margin ...]`,
    with demo tests for N = 2 and N = 3.
11. Later: the two-vehicle re-solve and the giant-tour split restart.

## Consequences

- The multi-route layer sits on the single-route solver and inherits its
  tested invariants; the checker is a second line of defence.
- Districts are contiguous, a street is never split between trucks, and
  boundaries prefer main roads, so routes are learnable and readable on a map.
- The work decomposes and runs in parallel without making the solver impure.
- The result is a strong heuristic, not a proven optimum: assigning streets to
  districts early can cost total time against a joint model. The exchange loop
  and the later re-solve and restart reduce that gap; the reported bound shows
  how large it can be.
- Most new tunables are stated defaults; the benchmark sets the search budgets.
- `starboard-solver` gains `scipy` (BSD-3-Clause) and `ortools` (Apache-2.0),
  both compatible with ADR-0001.
- Not modelled: trucks queueing at the shared disposal site, and staggered
  departures from the yard.

## References

- Ahr, D., Reinelt, G. (2006). A tabu search algorithm for the min-max k-Chinese postman problem. Computers & Operations Research 33(12). https://iaorifors.com/paper/55056
- Beasley, J.E. (1983). Route first, cluster second methods for vehicle routing. Omega 11(4). https://www.brunel.ac.uk/~mastjjb/jeb/abstracts/omega83.html
- Benavent, E., Soler, D. (1999). The Directed Rural Postman Problem with Turn Penalties. Transportation Science 33(4), 408-418. https://ideas.repec.org/a/inm/ortrsc/v33y1999i4p408-418.html
- Butsch, A., Kalcsics, J., Laporte, G. (2014). Districting for arc routing. INFORMS Journal on Computing 26(4), 809-824. https://researchportal.bath.ac.uk/en/publications/districting-for-arc-routing/
- Cortinhal, M.J., Mourão, M.C., Nunes, A.C. (2015). Local search heuristics for sectoring routing in a household waste collection context. CIO Working Paper 1/2015. https://ciencias.ulisboa.pt/sites/default/files/fcul/unidinvestig/cio/1.2015.pdf
- Karypis, G., Kumar, V. (1998). A Fast and High Quality Multilevel Scheme for Partitioning Irregular Graphs. SIAM Journal on Scientific Computing. https://www.cs.albany.edu/~jhh/courses/readings/karypis.siam98.metis.pdf
- Mei, Y., Li, X., Yao, X. (2014). Cooperative Coevolution With Route Distance Grouping for Large-Scale Capacitated Arc Routing Problems. IEEE Transactions on Evolutionary Computation 18(3). https://scholars.ln.edu.hk/en/publications/cooperative-coevolution-with-route-distance-grouping-for-large-sc/
- Mourão, M.C., Nunes, A.C., Prins, C. (2009). Heuristic methods for the sectoring arc routing problem. European Journal of Operational Research 196(3). https://ciencia.iscte-iul.pt/publications/heuristic-methods-for-the-sectoring-arc-routing-problem/10316
- Muyldermans, L., Cattrysse, D., Van Oudheusden, D. (2003). District design for arc-routing applications. Journal of the Operational Research Society 54(11). https://ideas.repec.org/a/pal/jorsoc/v54y2003i11d10.1057_palgrave.jors.2601626.html
- OR-Tools: Vehicle Routing Problem. https://developers.google.com/optimization/routing/vrp
- OR-Tools `routing_parameters.proto`. https://raw.githubusercontent.com/google/or-tools/stable/ortools/constraint_solver/routing_parameters.proto
- SciPy `scipy.sparse.csgraph.dijkstra`. https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.csgraph.dijkstra.html
- Tang, K., Wang, J., Li, X., Yao, X. (2017). A Scalable Approach to Capacitated Arc Routing Problems Based on Hierarchical Decomposition. IEEE Transactions on Cybernetics 47(11). https://scholars.ln.edu.hk/en/publications/a-scalable-approach-to-capacitated-arc-routing-problems-based-on-/
- Vidal, T. (2016). Split algorithm in O(n) for the capacitated vehicle routing problem. Computers & Operations Research 69. https://arxiv.org/abs/1508.02759
- Vidal, T. (2017). Node, edge, arc routing and turn penalties: multiple problems, one neighborhood extension. Operations Research. https://w1.cirrelt.ca/~vidalt/papers/NEARP-Vidal-Revision-WP.pdf
- Willemse, E.J., Joubert, J.W. (2016). Splitting procedures for the Mixed Capacitated Arc Routing Problem under Time restrictions with Intermediate Facilities. Operations Research Letters 44(5). https://repository.up.ac.za/bitstream/2263/56379/1/Willemse_Splitting_2016.pdf
