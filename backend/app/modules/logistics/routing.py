"""Road-route preview; saving the stop sequence is a separate reviewed operation."""

import httpx
from sqlalchemy import select

from app.modules.logistics.policy import policy
from app.modules.logistics.service import decode, trip_facts
from app.modules.orders.models import Order
from app.shared.exceptions.api_error import ApiError

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"


def waypoint(coordinate):
    return {"location": {"latLng": coordinate}}


async def optimize(service, row):
    config = await policy(service.session, service.merchant_id)
    key = service.settings.logistics_routes_api_key
    if not config.optimizationEnabled or not key:
        raise ApiError(
            "ROUTING_UNAVAILABLE",
            503,
            "Route optimization is not configured. Save a manual sequence or ask Admin to configure the routing provider.",
        )
    if row.status not in ("DRAFT", "READY"):
        raise ApiError(
            "ROUTE_PREVIEW_CLOSED",
            409,
            "Optimize before the trip starts; update remaining stops manually after departure.",
        )
    pairs, _ = await trip_facts(service.session, row.id)
    if any(
        (stop.latitude if stop.latitude is not None else s.destination_latitude) is None
        or (stop.longitude if stop.longitude is not None else s.destination_longitude) is None
        for stop, s in pairs
    ):
        raise ApiError(
            "ROUTE_COORDINATES_REQUIRED",
            422,
            "Every stop needs a saved delivery-location coordinate. Manual sequencing remains available.",
        )
    origin = waypoint(decode(row.origin))
    destination = waypoint(decode(row.destination))
    stops = [
        waypoint(
            {
                "latitude": stop.latitude if stop.latitude is not None else s.destination_latitude,
                "longitude": stop.longitude
                if stop.longitude is not None
                else s.destination_longitude,
            }
        )
        for stop, s in pairs
    ]
    headers = {
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "routes.optimizedIntermediateWaypointIndex,routes.distanceMeters,routes.duration",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=25) as client:

        async def request(points, opt):
            try:
                result = await client.post(
                    ROUTES_URL,
                    headers=headers,
                    json={
                        "origin": origin,
                        "destination": destination,
                        "intermediates": points,
                        "travelMode": "DRIVE",
                        "optimizeWaypointOrder": opt,
                    },
                )
                result.raise_for_status()
                routes = result.json().get("routes", [])
                if not routes:
                    raise ValueError("No drivable route")
                return routes[0]
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                raise ApiError(
                    "ROUTING_PROVIDER_FAILED",
                    503,
                    "The routing provider could not calculate this route. Keep the current sequence and retry later.",
                ) from exc

        result = await request(stops, True)
        indices = result.get("optimizedIntermediateWaypointIndex", list(range(len(stops))))
        if sorted(indices) != list(range(len(stops))):
            raise ApiError("ROUTING_PROVIDER_FAILED", 503)
        ordered = [pairs[i] for i in indices]
        if config.priorityFirst:
            priorities = {p.code: p.rank for p in config.priorities}
            orders = {
                o.id: o
                for o in (
                    await service.session.scalars(
                        select(Order).where(Order.id.in_([s.order_id for stop, s in pairs]))
                    )
                ).all()
            }
            ordered.sort(
                key=lambda p: priorities.get(
                    orders[p[1].order_id].priority_code, priorities[config.defaultPriority]
                )
            )
        movable = [p for p in ordered if not p[0].pinned]
        final = [p if p[0].pinned else movable.pop(0) for p in pairs]
        # Recalculate distance/time for the actual constrained sequence, rather than showing
        # provider estimates for a different unpinned/unprioritized order.
        points = [
            waypoint(
                {
                    "latitude": stop.latitude
                    if stop.latitude is not None
                    else s.destination_latitude,
                    "longitude": stop.longitude
                    if stop.longitude is not None
                    else s.destination_longitude,
                }
            )
            for stop, s in final
        ]
        measured = await request(points, False)
    return {
        "deliveryIds": [s.id for stop, s in final],
        "distanceMeters": measured.get("distanceMeters"),
        "duration": measured.get("duration"),
        "provider": "GOOGLE_ROUTES",
        "estimated": True,
        "priorityFirst": config.priorityFirst,
        "approved": False,
    }
