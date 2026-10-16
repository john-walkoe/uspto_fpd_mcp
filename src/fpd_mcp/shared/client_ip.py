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

CR-02 (review 2026-09-28): a typical deployment sits behind Cloudflare ->
cloudflared -> a reverse-proxy container -> this container, all inside one
Docker network such as `172.18.0.0/16`, so the ASGI socket peer FPD ever sees
is the reverse proxy's address — declaring that ONE CIDR is enough to trust
the hop. Reading `X-Forwarded-For`'s rightmost-untrusted-hop was the only
signal before this pass, but the reverse proxy's own forwarding can insert an
extra local hop (e.g. the cloudflared loopback address) ahead of the real
client, which would require separately declaring THAT hop too just to strip
it off. `CF-Connecting-IP` does not have this problem: Cloudflare sets it at
its edge and it survives unmodified through every hop in between, so once
the immediate peer is trusted, `CF-Connecting-IP` alone is the real client
address — no second CIDR needed. Prefer it; fall back to the
rightmost-untrusted `X-Forwarded-For` hop when it is absent (self-hosters
behind a plain nginx/Traefik reverse proxy that does not set it).
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


def collapse_ipv6(address: str) -> str:
    """Collapse an IPv6 address to its /56 for rate-limit keying: a caller
    who owns a /56 (a common residential or cloud allocation) must not be
    able to rotate through it for a fresh bucket per address. IPv4 addresses
    and anything that fails to parse pass through unchanged."""
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return address
    if isinstance(parsed, ipaddress.IPv6Address):
        return str(ipaddress.ip_network(f"{parsed}/56", strict=False).network_address)
    return address


def resolve_client_ip(
    peer: Optional[str],
    forwarded_for: Optional[str] = None,
    cf_connecting_ip: Optional[str] = None,
) -> str:
    """The caller's address, honoring proxy headers only from a declared proxy.

    Args:
        peer: the raw ASGI peer address (`request.client.host`).
        forwarded_for: the `X-Forwarded-For` header value, if any.
        cf_connecting_ip: the `CF-Connecting-IP` header value, if any.

    Returns the peer address unless the peer is a trusted proxy, in which
    case `CF-Connecting-IP` is used when present and parseable (CR-02: it
    survives every intermediate hop unmodified once Cloudflare sets it, so
    trusting the one immediate-peer CIDR is sufficient), else the RIGHTMOST
    `X-Forwarded-For` entry that is not itself a trusted proxy — the last hop
    the trusted chain actually observed, rather than the leftmost value,
    which the client controls. The result is collapsed to a /56 for IPv6.
    """
    peer = (peer or "").strip() or _UNKNOWN
    networks = trusted_proxy_networks()
    if not networks or not _in_networks(peer, networks):
        return collapse_ipv6(peer)
    cf_connecting_ip = (cf_connecting_ip or "").strip()
    if cf_connecting_ip:
        try:
            ipaddress.ip_address(cf_connecting_ip)
        except ValueError:
            pass
        else:
            return collapse_ipv6(cf_connecting_ip)
    if not forwarded_for:
        return collapse_ipv6(peer)
    candidates = [part.strip() for part in forwarded_for.split(",") if part.strip()]
    for candidate in reversed(candidates):
        if _in_networks(candidate, networks):
            continue
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        return collapse_ipv6(candidate)
    return collapse_ipv6(peer)


def client_ip_from_request(request: Any) -> str:
    """resolve_client_ip for a Starlette/FastAPI Request."""
    client = getattr(request, "client", None)
    peer = getattr(client, "host", None) if client is not None else None
    headers = getattr(request, "headers", None)
    forwarded = headers.get("x-forwarded-for") if headers is not None else None
    cf_connecting_ip = headers.get("cf-connecting-ip") if headers is not None else None
    return resolve_client_ip(peer, forwarded, cf_connecting_ip)
