"""Resolve the caller's address behind an optional trusted reverse proxy.

M-1: the IP allowlist and every rate limiter keyed on `request.client.host`,
the raw ASGI peer address. Behind an API gateway or reverse proxy that is ONE
value for the whole internet, so the allowlist admits everyone the proxy
admits and both limiters throttle all callers as if they were a single
client. The previous design note was right that `X-Forwarded-For` must not be
trusted from an arbitrary caller — it is trivially spoofable — so the header
is read only when the peer itself is an operator-declared proxy.

`FPD_TRUSTED_PROXY_IPS` (comma-separated IPs or CIDRs) is empty by default,
which reproduces the previous behavior exactly: no header is consulted and
the peer address is used as-is.
"""

import ipaddress
import os
from typing import Any, List, Optional

_UNKNOWN = "unknown"


def trusted_proxy_networks() -> List[Any]:
    """Parse FPD_TRUSTED_PROXY_IPS into ip_network objects."""
    networks: List[Any] = []
    for entry in os.getenv("FPD_TRUSTED_PROXY_IPS", "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            # Logged by the caller's own logger if it cares; a malformed
            # entry must not be treated as a match.
            continue
    return networks


def _in_networks(address: str, networks: List[Any]) -> bool:
    if not networks:
        return False
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(parsed in network for network in networks)


def resolve_client_ip(
    peer: Optional[str], forwarded_for: Optional[str] = None
) -> str:
    """The caller's address, honoring XFF only from a declared proxy.

    Args:
        peer: the raw ASGI peer address (`request.client.host`).
        forwarded_for: the `X-Forwarded-For` header value, if any.

    Returns the peer address unless the peer is a trusted proxy AND the
    header carries a parseable address, in which case the RIGHTMOST entry
    that is not itself a trusted proxy is used — the last hop the trusted
    chain actually observed, rather than the leftmost value, which the client
    controls.
    """
    peer = (peer or "").strip() or _UNKNOWN
    networks = trusted_proxy_networks()
    if not networks or not _in_networks(peer, networks):
        return peer
    if not forwarded_for:
        return peer
    candidates = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    for candidate in reversed(candidates):
        if _in_networks(candidate, networks):
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return candidate
    return peer


def client_ip_from_request(request: Any) -> str:
    """resolve_client_ip for a Starlette/FastAPI Request."""
    client = getattr(request, "client", None)
    peer = getattr(client, "host", None) if client is not None else None
    headers = getattr(request, "headers", None)
    forwarded = headers.get("x-forwarded-for") if headers is not None else None
    return resolve_client_ip(peer, forwarded)
