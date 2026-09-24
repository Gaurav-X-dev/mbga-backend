"""Geolocation utilities for delivery proximity checks."""

from __future__ import annotations

import math


def haversine_distance_meters(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Calculate the great-circle distance in **meters** between two GPS
    coordinates using the Haversine formula.

    Parameters
    ----------
    lat1, lon1 : float
        Latitude/longitude of point A in decimal degrees.
    lat2, lon2 : float
        Latitude/longitude of point B in decimal degrees.

    Returns
    -------
    float
        Distance in meters.
    """
    R = 6_371_000  # Earth radius in meters

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# Default geofence radius used by the delivery-start proximity check (§7.1).
DEFAULT_GEOFENCE_RADIUS_METERS: float = 200.0
