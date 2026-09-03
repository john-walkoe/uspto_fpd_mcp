"""Controls that read correctly in source but collapse in the deployment.

M-1  the IP allowlist and every rate limiter keyed on the raw ASGI peer,
     which behind a reverse proxy is one value for the whole internet
M-5  /register was the one unrated OAuth route, and _client_cache was an
     unbounded dict fed by whatever client_ids arrived
M-7  deactivation took effect only at the next token refresh
M-15 the container ran as root over the shared auth-DB bind mount
M-18 the 100 MB PDF cap bounded ONE download; nothing bounded how many were
     buffered at once
"""

import re
from pathlib import Path

import pytest

from fpd_mcp.shared.client_ip import resolve_client_ip

REPO = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------- M-1


def test_the_peer_address_is_used_when_no_proxy_is_declared(monkeypatch):
    """Default behavior is byte-for-byte what it was: no header consulted."""
    monkeypatch.delenv("FPD_TRUSTED_PROXY_IPS", raising=False)

    assert resolve_client_ip("10.0.0.5", "203.0.113.9") == "10.0.0.5"


def test_a_spoofed_forwarded_header_is_ignored_from_an_untrusted_peer(monkeypatch):
    monkeypatch.setenv("FPD_TRUSTED_PROXY_IPS", "172.18.0.0/16")

    assert resolve_client_ip("203.0.113.50", "1.2.3.4") == "203.0.113.50"


def test_a_trusted_proxy_reveals_the_real_client(monkeypatch):
    monkeypatch.setenv("FPD_TRUSTED_PROXY_IPS", "172.18.0.0/16")

    assert resolve_client_ip("172.18.0.2", "203.0.113.9") == "203.0.113.9"


def test_the_rightmost_non_proxy_hop_wins(monkeypatch):
    """The leftmost entry is client-controlled; the rightmost non-proxy hop
    is the last address the trusted chain actually observed."""
    monkeypatch.setenv("FPD_TRUSTED_PROXY_IPS", "172.18.0.0/16")

    resolved = resolve_client_ip(
        "172.18.0.2", "9.9.9.9, 203.0.113.9, 172.18.0.3"
    )

    assert resolved == "203.0.113.9"


@pytest.mark.parametrize("garbage", ["", "not-an-ip", ",,,"])
def test_a_garbage_forwarded_header_falls_back_to_the_peer(monkeypatch, garbage):
    monkeypatch.setenv("FPD_TRUSTED_PROXY_IPS", "172.18.0.0/16")

    assert resolve_client_ip("172.18.0.2", garbage) == "172.18.0.2"


def test_a_malformed_trusted_proxy_entry_never_matches(monkeypatch):
    monkeypatch.setenv("FPD_TRUSTED_PROXY_IPS", "not-a-cidr")

    assert resolve_client_ip("172.18.0.2", "203.0.113.9") == "172.18.0.2"


# --------------------------------------------------------------------- M-5


def test_register_is_rate_limited_like_authorize_and_token():
    source = (REPO / "src" / "fpd_mcp" / "auth" / "provider.py").read_text()

    match = re.search(
        r'getattr\(route, "path", None\) in \(([^)]*)\)', source
    )
    assert match, "the rate-limited route list moved"
    limited = match.group(1)
    assert '"/register"' in limited
    assert '"/authorize"' in limited and '"/token"' in limited


def test_the_oauth_client_cache_is_bounded():
    from collections import OrderedDict

    from fpd_mcp.auth import provider as provider_module

    class _Bare:
        _client_cache = OrderedDict()
        _cache_client = provider_module.FpdAuthProvider._cache_client

    bare = _Bare()
    bare._client_cache = OrderedDict()
    for i in range(provider_module._MAX_CACHED_CLIENTS + 25):
        bare._cache_client(f"client-{i}", object())

    assert len(bare._client_cache) == provider_module._MAX_CACHED_CLIENTS
    assert "client-0" not in bare._client_cache


# --------------------------------------------------------------------- M-7


async def test_deactivation_revokes_live_refresh_tokens(tmp_path):
    """M-7: a deactivated user could keep refreshing indefinitely."""
    from fpd_mcp.auth.store import McpUserStore

    store = McpUserStore(str(tmp_path / "auth.db"))
    await store.upsert_user("alice@example.com", role="user")
    await store.put_refresh(
        "refresh-token-1",
        client_id="client-a",
        email="alice@example.com",
        scopes=["fpd:user"],
        ttl_seconds=3600,
    )

    assert await store.get_refresh("refresh-token-1") is not None

    assert await store.set_active("alice@example.com", False) is True

    assert await store.get_refresh("refresh-token-1") is None


async def test_reactivation_does_not_revoke_anything(tmp_path):
    from fpd_mcp.auth.store import McpUserStore

    store = McpUserStore(str(tmp_path / "auth.db"))
    await store.upsert_user("bob@example.com", role="user")
    await store.put_refresh(
        "refresh-token-2",
        client_id="client-a",
        email="bob@example.com",
        scopes=["fpd:user"],
        ttl_seconds=3600,
    )

    await store.set_active("bob@example.com", True)

    assert await store.get_refresh("refresh-token-2") is not None


# -------------------------------------------------------------------- M-15


def test_the_container_does_not_run_as_root():
    dockerfile = (REPO / "Dockerfile").read_text()

    assert re.search(r"^USER\s+app\s*$", dockerfile, re.MULTILINE), dockerfile


# -------------------------------------------------------------------- M-18


def test_the_pdf_cap_is_petition_realistic(monkeypatch):
    import fpd_mcp.api.fpd_client as fpd_client_module

    assert fpd_client_module._MAX_PDF_BYTES == 25 * 1024 * 1024


def test_concurrent_extractions_are_bounded():
    import fpd_mcp.api.fpd_client as fpd_client_module

    assert (
        fpd_client_module._extraction_slots._value
        == fpd_client_module._MAX_CONCURRENT_EXTRACTIONS
    )
    assert fpd_client_module._MAX_CONCURRENT_EXTRACTIONS < 10
