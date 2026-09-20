"""Client IP address, honouring X-Forwarded-For only from trusted reverse proxies."""

import ipaddress

from fastapi import Request


def _parse(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _is_trusted(address, trusted: list[str]) -> bool:
    for entry in trusted:
        try:
            if address in ipaddress.ip_network(entry.strip(), strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request, trusted_proxies: list[str]) -> str | None:
    peer = _parse(request.client.host) if request.client else None
    if peer is None:
        return None
    if not trusted_proxies or not _is_trusted(peer, trusted_proxies):
        return str(peer)
    # Walk the chain from the right; the first address that is not a trusted proxy is the client.
    forwarded = request.headers.get("x-forwarded-for", "")
    for hop in reversed([part for part in forwarded.split(",") if part.strip()]):
        address = _parse(hop)
        if address is None:
            return str(peer)
        if not _is_trusted(address, trusted_proxies):
            return str(address)
    return str(peer)
