"""The browser's IP address behind the reverse proxies.

Production: TLS nginx (app.conf) -> gateway nginx (gateway.conf) -> BFF. Both append to
X-Forwarded-For, so the chain reads "<client>, <proxy>...". Walking it from the right and skipping
trusted proxy addresses gives the first address a proxy we control actually saw. A client can
prepend fake entries, but cannot change what our own proxies append. Used only for the approximate
location and the 30-day security record; never for an access decision.
"""
from __future__ import annotations

import ipaddress
from functools import lru_cache

from app.core.config import get_settings


@lru_cache(maxsize=8)
def _networks(cidrs: tuple[str, ...]):
    return tuple(ipaddress.ip_network(value, strict=False) for value in cidrs)


def _parse(value: str):
    try:
        address = ipaddress.ip_address(value.strip().strip("[]"))
    except ValueError:
        return None
    return address.ipv4_mapped or address if address.version == 6 else address


def client_ip(peer: str | None, forwarded_for: str | None) -> str | None:
    trusted = _networks(tuple(get_settings().session_trusted_proxy_cidrs))
    chain = [item for item in (forwarded_for or "").split(",")[-20:] if item.strip()]
    candidates = [_parse(item) for item in chain] + [_parse(peer or "")]
    candidates = [item for item in candidates if item is not None]
    if not candidates:
        return None
    peer_address = candidates[-1]
    if not any(peer_address in network for network in trusted):
        return str(peer_address)  # not behind a proxy we trust: ignore the header
    for address in reversed(candidates):
        if not any(address in network for network in trusted):
            return str(address)
    return str(candidates[0])  # everything is internal (local development)
