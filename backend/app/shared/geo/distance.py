"""Distance between two points on the earth.

Used for one thing: telling a driver how far they still are from the delivery gate. That is a
display number and a soft check, never an authorisation - a driver whose GPS is drifting must
still be able to complete a delivery they are standing in front of.

The great-circle distance is accurate to well under a metre at delivery range, which is orders
of magnitude better than the handset's own fix. Nothing here needs a projection or a geo
extension, so there is no dependency and no PostGIS-shaped hole in a MySQL deployment.
"""

from math import asin, cos, radians, sin, sqrt

#: Mean earth radius, metres (IUGG).
EARTH_RADIUS_METRES = 6_371_008.8


def haversine_metres(
    latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
) -> float:
    """Great-circle distance between two WGS-84 points, in metres."""
    lat_a, lon_a, lat_b, lon_b = map(radians, (latitude_a, longitude_a, latitude_b, longitude_b))
    d_lat = lat_b - lat_a
    d_lon = lon_b - lon_a
    h = sin(d_lat / 2) ** 2 + cos(lat_a) * cos(lat_b) * sin(d_lon / 2) ** 2
    return 2 * EARTH_RADIUS_METRES * asin(sqrt(h))
