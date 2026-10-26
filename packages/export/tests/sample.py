"""A small run to export: two trucks, a street name that needs escaping, an unknown stop."""

from starboard.export.model import RunExport, Step, StopInfo, TruckRoute

RUN = RunExport(
    route_name="Byram & Mill",
    osm_snapshot="2026-10-01",
    routes=(
        TruckRoute(
            order=("s2", "s1"),
            path=((-73.65, 41.0), (-73.649, 41.0), (-73.649, 41.001)),
            steps=(
                Step("depart", "Mill St", 120.0, ("s2", "s1")),
                Step("unload", None, 0.0, ()),
                Step("arrive", None, 0.0, ()),
            ),
            route_time_s=3600.0,
            distance_m=1200.0,
        ),
        TruckRoute(
            order=("s3", "s9"),
            path=((-73.651, 41.002), (-73.652, 41.002)),
            steps=(
                Step("depart", "Byram Rd", 80.0, ("s3",)),
                Step("left", "Ole's <Lane>", 40.0, ("s9",)),
                Step("arrive", None, 0.0, ()),
            ),
            route_time_s=1800.0,
            distance_m=800.0,
        ),
    ),
    stops={
        "s1": StopInfo("s1", "Mill St", -73.6495, 41.0001, None, 1),
        "s2": StopInfo("s2", "Mill St", -73.6497, 41.0001, None, 2),
        "s3": StopInfo("s3", "Byram Rd", -73.6511, 41.0021, None, 3),
    },
)
