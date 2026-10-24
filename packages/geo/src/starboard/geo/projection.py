"""Local planar coordinates in metres for a town-sized area.

An equirectangular projection about a reference latitude: x is metres east,
y metres north. Over a few kilometres its distance error is well under 0.1%,
which is far below address-point accuracy.
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass

from starboard.solver.graph import LonLat

# IUGG mean Earth radius R1 for WGS 84: https://en.wikipedia.org/wiki/Earth_radius#Mean_radii
EARTH_MEAN_RADIUS_M = 6_371_008.8


@dataclass(frozen=True, slots=True)
class LocalProjection:
    origin: LonLat

    @classmethod
    def centred_on(cls, points: Iterable[LonLat]) -> "LocalProjection":
        lons: list[float] = []
        lats: list[float] = []
        for point in points:
            lons.append(point.lon)
            lats.append(point.lat)
        if not lons:
            raise ValueError("cannot centre a projection on no points")
        return cls(LonLat(lon=sum(lons) / len(lons), lat=sum(lats) / len(lats)))

    def to_xy(self, point: LonLat) -> tuple[float, float]:
        metres_per_radian = EARTH_MEAN_RADIUS_M
        x = (
            math.radians(point.lon - self.origin.lon)
            * metres_per_radian
            * math.cos(math.radians(self.origin.lat))
        )
        y = math.radians(point.lat - self.origin.lat) * metres_per_radian
        return x, y

    def to_lonlat(self, x: float, y: float) -> LonLat:
        lat = self.origin.lat + math.degrees(y / EARTH_MEAN_RADIUS_M)
        lon = self.origin.lon + math.degrees(
            x / (EARTH_MEAN_RADIUS_M * math.cos(math.radians(self.origin.lat)))
        )
        return LonLat(lon=lon, lat=lat)


def heading_deg(dx: float, dy: float) -> float:
    """Compass heading of a planar vector: 0 is north, 90 east, in [0, 360)."""
    return math.degrees(math.atan2(dx, dy)) % 360.0


def heading_change_deg(exit_heading: float, entry_heading: float) -> float:
    """Signed change from one heading to another, in (-180, 180]; positive turns right."""
    change = (entry_heading - exit_heading) % 360.0
    return change - 360.0 if change > 180.0 else change
