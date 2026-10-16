"""Owner-only admin and the honored OAuth scope (Wave 2 Part A item 1).

Shared with the sibling USPTO servers:
- a token carries the scopes the client REQUESTED, intersected with what the
  account holds (a request naming no scope gets fpd:user);
- with FPD_OWNER_EMAILS set, only an owner account holds fpd:admin, and a
  token minted before the list existed loses the scope at bearer load;
- only an owner email may grant the admin role through FPD_manage_users.
A client that requests user scope only never receives admin.
"""

import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from fpd_mcp.auth.provider import (
    SCOPE_ADMIN,
    SCOPE_USER,
    FpdAuthProvider,
    admin_allowed_for,
    build_auth_provider,
    scopes_for_user,
)
from fpd_mcp.auth.settings import AuthSettings
from fpd_mcp.tools import admin

from test_auth_provider import (  # tests/ is on sys.path, as for test_tools_misc
    FakeUserStore,
    get_request,
    make_client,
    make_params,
    make_settings,
    txn_cookie,
)

OWNER = "owner@example.com"


def _provider(owners: str = OWNER, **overrides: Any):
    store = FakeUserStore()
    provider = FpdAuthProvider(
        make_settings(auth_owner_emails=owners, **overrides), store)  # type: ignore[arg-type]
    for email, role in ((OWNER, "admin"), ("admin@firm.com", "admin"),
                        ("jane@firm.com", "user")):
        store.users[email] = {"email": email, "role": role, "active": True,
                              "display_name": None, "last_login_idp": "google"}
    return provider, store


async def _granted(provider, store, monkeypatch, email, scopes):
    """Run one sign-in and return the scopes the issued code carries."""
    url = await provider.authorize(make_client(), make_params(scopes=scopes))
    txn = parse_qs(urlparse(url).query)["txn"][0]

    async def fake_exchange(idp_, code, nonce):
        return {"email": email, "email_verified": True}

    monkeypatch.setattr(provider, "_exchange_and_verify", fake_exchange)
    resp = await provider._callback_endpoint(get_request(
        "/auth/callback/google", f"state={txn}&code=up", {"idp": "google"},
        cookies=txn_cookie(provider, txn)))
    assert resp.status_code == 302
    code = parse_qs(urlparse(resp.headers["location"]).query)["code"][0]
    return store.codes[code]["scopes"]


class TestSettings:
    def test_owner_emails_parse_from_the_env(self, monkeypatch):
        monkeypatch.setenv("FPD_OWNER_EMAILS", " Owner@Example.com, second@example.org ,")

        assert AuthSettings.from_env().owner_emails == frozenset(
            {"owner@example.com", "second@example.org"})

    def test_unset_means_no_owner_list(self, monkeypatch):
        monkeypatch.delenv("FPD_OWNER_EMAILS", raising=False)

        assert AuthSettings.from_env().owner_emails == frozenset()

    def test_the_rule(self):
        owners = frozenset({OWNER})
        assert admin_allowed_for("x@y.com", frozenset()) is True
        assert admin_allowed_for("Owner@Example.com ", owners) is True
        assert admin_allowed_for("admin@firm.com", owners) is False
        assert scopes_for_user("admin", "admin@firm.com", owners) == [SCOPE_USER]
        assert scopes_for_user("admin", OWNER, owners) == [SCOPE_USER, SCOPE_ADMIN]
        assert scopes_for_user("user", OWNER, owners) == [SCOPE_USER]

    def test_startup_warns_when_no_owner_list_is_set(self, caplog):
        with caplog.at_level(logging.WARNING):
            build_auth_provider(make_settings(), FakeUserStore())  # type: ignore[arg-type]

        assert "FPD_OWNER_EMAILS is not set" in caplog.text

    def test_no_warning_with_an_owner_list(self, caplog):
        with caplog.at_level(logging.WARNING):
            build_auth_provider(
                make_settings(auth_owner_emails=OWNER), FakeUserStore())  # type: ignore[arg-type]

        assert "FPD_OWNER_EMAILS is not set" not in caplog.text


class TestRequestedScopeIsHonored:
    async def test_an_owner_asking_for_admin_gets_it(self, monkeypatch):
        provider, store = _provider()
        scopes = await _granted(provider, store, monkeypatch, OWNER, [SCOPE_USER, SCOPE_ADMIN])

        assert scopes == [SCOPE_USER, SCOPE_ADMIN]

    async def test_an_owner_asking_for_user_gets_user_only(self, monkeypatch):
        """A client that requests user scope only: no admin scope."""
        provider, store = _provider()
        scopes = await _granted(provider, store, monkeypatch, OWNER, [SCOPE_USER])

        assert scopes == [SCOPE_USER]

    async def test_a_request_naming_no_scope_gets_user(self, monkeypatch):
        provider, store = _provider()
        scopes = await _granted(provider, store, monkeypatch, OWNER, None)

        assert scopes == [SCOPE_USER]

    async def test_a_non_owner_roster_admin_never_gets_admin(self, monkeypatch):
        provider, store = _provider()
        scopes = await _granted(provider, store, monkeypatch, "admin@firm.com",
                                [SCOPE_USER, SCOPE_ADMIN])

        assert scopes == [SCOPE_USER]

    async def test_without_an_owner_list_a_roster_admin_still_can(self, monkeypatch):
        provider, store = _provider(owners="")
        scopes = await _granted(provider, store, monkeypatch, "admin@firm.com",
                                [SCOPE_USER, SCOPE_ADMIN])

        assert scopes == [SCOPE_USER, SCOPE_ADMIN]

    async def test_the_code_carries_the_requested_bound_to_the_tokens(self, monkeypatch):
        provider, store = _provider()
        client = make_client()
        await _granted(provider, store, monkeypatch, OWNER, [SCOPE_USER])
        code_id = next(iter(store.codes))
        store.codes[code_id]["client_id"] = client.client_id

        code = await provider.load_authorization_code(client, code_id)
        token = await provider.exchange_authorization_code(client, code)

        assert code.requested_scopes == [SCOPE_USER]
        assert store.refresh[token.refresh_token]["scopes"] == [SCOPE_USER]

    async def test_refresh_stays_inside_the_requested_bound(self):
        provider, store = _provider()
        client = make_client()
        await store.put_refresh("r-1", client_id=client.client_id, email=OWNER,
                                scopes=[SCOPE_USER], ttl_seconds=3600)

        loaded = await provider.load_refresh_token(client, "r-1")
        token = await provider.exchange_refresh_token(client, loaded, [])
        access = await provider.load_access_token(token.access_token)

        assert access.scopes == [SCOPE_USER]
        # The bound travels on: the next refresh row carries it.
        assert store.refresh[token.refresh_token]["scopes"] == [SCOPE_USER]

    async def test_refresh_never_grants_admin_to_a_non_owner(self):
        provider, store = _provider()
        client = make_client()
        await store.put_refresh("r-2", client_id=client.client_id, email="admin@firm.com",
                                scopes=[SCOPE_USER, SCOPE_ADMIN], ttl_seconds=3600)

        loaded = await provider.load_refresh_token(client, "r-2")
        token = await provider.exchange_refresh_token(client, loaded, [])
        access = await provider.load_access_token(token.access_token)

        assert access.scopes == [SCOPE_USER]


class TestBearerLoad:
    async def test_admin_is_stripped_from_an_already_issued_non_owner_token(self):
        # Minted while no owner list was set...
        issuer, _ = _provider(owners="")
        token = await issuer._issue_tokens(
            client_id="c", email="admin@firm.com", scopes=[SCOPE_USER, SCOPE_ADMIN],
            idp="google", display_name=None, role="admin")
        # ...presented after FPD_OWNER_EMAILS was set (same JWT secret).
        provider, _ = _provider()

        access = await provider.load_access_token(token.access_token)

        assert access is not None
        assert access.scopes == [SCOPE_USER]

    async def test_an_owner_token_keeps_admin(self):
        provider, _ = _provider()
        token = await provider._issue_tokens(
            client_id="c", email=OWNER, scopes=[SCOPE_USER, SCOPE_ADMIN],
            idp="google", display_name=None, role="admin")

        access = await provider.load_access_token(token.access_token)

        assert access.scopes == [SCOPE_USER, SCOPE_ADMIN]

    async def test_the_operator_admin_bearer_keeps_admin(self):
        provider, _ = _provider(auth_internal_admin_token="a" * 40)

        access = await provider.load_access_token("a" * 40)

        assert access.scopes == [SCOPE_USER, SCOPE_ADMIN]
        assert access.subject == "internal-admin"

    async def test_the_plain_internal_bearer_is_still_user_only(self):
        provider, _ = _provider()

        access = await provider.load_access_token("internal-static-token")

        assert access.scopes == [SCOPE_USER]


# ---------------------------------------------------------------------------
# FPD_manage_users: the grant rule
# ---------------------------------------------------------------------------

class _Store:
    def __init__(self):
        self.upserts = []

    async def get_user(self, email):
        return {"email": email, "role": "admin", "active": True}

    async def upsert_user(self, email, **kwargs):
        self.upserts.append((email, kwargs.get("role")))

    async def set_active(self, email, active):
        return True

    async def list_users(self):
        return []


@pytest.fixture
def oauth_tool(monkeypatch):
    store = _Store()
    audits = []
    monkeypatch.setattr(admin, "_owner_emails", frozenset({OWNER}))
    monkeypatch.setattr(admin, "_get_user_store", lambda: store)
    monkeypatch.setattr(admin, "_audit_user_management",
                        lambda *a, **k: audits.append(a))
    caller = {"id": OWNER}
    monkeypatch.setattr(admin, "get_authenticated_identity", lambda: caller["id"])
    store.audits = audits
    return store, caller


class TestRegistration:
    def test_register_reads_the_owner_list_off_the_provider(self, monkeypatch):
        provider, _ = _provider()
        monkeypatch.setattr(admin, "USER_MANAGEMENT_ENABLED", False)
        monkeypatch.setattr(admin, "_owner_emails", None)
        monkeypatch.setattr(admin, "_user_store", None)

        admin.register(object(), provider)

        assert admin._owner_emails == frozenset({OWNER})

    def test_no_provider_means_no_per_identity_caller(self, monkeypatch):
        monkeypatch.setattr(admin, "USER_MANAGEMENT_ENABLED", False)
        monkeypatch.setattr(admin, "_owner_emails", frozenset({OWNER}))
        monkeypatch.setattr(admin, "_user_store", None)

        admin.register(object(), None)

        assert admin._owner_emails is None


class TestAdminGrant:
    async def test_an_owner_grants_admin(self, oauth_tool):
        store, _ = oauth_tool

        result = await admin.fpd_manage_users(action="add", email="new@firm.com", role="admin")

        assert "error" not in result
        assert store.upserts == [("new@firm.com", "admin")]

    async def test_the_operator_bearer_cannot_grant_admin(self, oauth_tool):
        store, caller = oauth_tool
        caller["id"] = "internal-admin"

        result = await admin.fpd_manage_users(
            action="set_role", email="new@firm.com", role="admin")

        assert result["error"] == "only an owner of this deployment may grant the admin role"
        assert result["status_code"] == 403
        assert store.upserts == []
        assert store.audits[0][4] is False  # audited as a failed attempt

    async def test_a_non_owner_admin_cannot_grant_admin(self, oauth_tool):
        store, caller = oauth_tool
        caller["id"] = "admin@firm.com"

        result = await admin.fpd_manage_users(action="add", email="x@firm.com", role="admin")

        assert "owner" in result["error"]
        assert store.upserts == []

    async def test_granting_user_needs_no_owner(self, oauth_tool):
        store, caller = oauth_tool
        caller["id"] = "internal-admin"

        result = await admin.fpd_manage_users(action="add", email="x@firm.com", role="user")

        assert "error" not in result
        assert store.upserts == [("x@firm.com", "user")]

    async def test_without_an_owner_list_a_roster_admin_still_grants(self, oauth_tool,
                                                                      monkeypatch):
        store, caller = oauth_tool
        monkeypatch.setattr(admin, "_owner_emails", frozenset())
        caller["id"] = "admin@firm.com"

        result = await admin.fpd_manage_users(action="add", email="x@firm.com", role="admin")

        assert "error" not in result

