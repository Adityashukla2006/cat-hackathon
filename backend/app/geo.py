"""Small geodesy helpers for site coordinates."""

from math import asin, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000.0
METERS_PER_DEG_LAT = 111_320.0


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters."""
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def offset(lat: float, lon: float, north_m: float, east_m: float) -> tuple[float, float]:
    """Move a point by a local north/east offset in meters."""
    return (
        lat + north_m / METERS_PER_DEG_LAT,
        lon + east_m / (METERS_PER_DEG_LAT * cos(radians(lat))),
    )
