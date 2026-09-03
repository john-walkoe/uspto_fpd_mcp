"""Dual-IdP OAuth 2.1 authorization server (Google + Microsoft Entra ID).

MCP clients (Claude.ai, Claude Desktop, ChatGPT) expect the MCP OAuth flow —
discovery metadata, Dynamic Client Registration, PKCE — but neither Google nor
Entra ID supports DCR, and FastMCP's OAuthProxy bridges exactly one upstream
IdP. This provider is the in-house bridge for two (ported from edgar_mcp via citations):

- The MCP-facing side (DCR, /authorize, /token, PKCE validation, metadata) is
  inherited from FastMCP's ``OAuthProvider`` / the MCP SDK's auth routes.
- ``authorize()`` parks the client's request as a transaction and sends the
  browser to a chooser page (/auth/select) with a Microsoft and a Google
  button; the callback verifies the upstream id_token against the IdP's JWKS.
- Authorization is decided by the ``mcp_users`` table, not by the IdP: a login
  succeeds only when the verified email maps to an active row. role 'admin'
  adds the ``fpd:admin`` scope, which per-identity unhides the
  user-management tool (see main.py).
- Access tokens are short-lived HS256 JWTs minted by this server (FastMCP's
  JWTIssuer); refresh tokens rotate on every use and re-check the user row,
  so deactivating a user takes effect at the next refresh.
- Headless internal clients (internal gateways / Claude Code) present the
  static ``FPD_AUTH_INTERNAL_TOKEN`` as a bearer and skip the flow.

State that must survive restarts (registered clients, auth codes, refresh
tokens) lives in SQLite via ``McpUserStore``; in-flight login transactions
are in-memory (a restart mid-login just means one retried sign-in).
"""
from __future__ import annotations

import logging
from collections import OrderedDict
import os
import secrets
import threading
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode, urlparse

import httpx
from fastmcp.server.auth.auth import AccessToken, OAuthProvider
from fastmcp.server.auth.jwt_issuer import JWTIssuer, derive_jwt_key
from joserfc import jwk
from joserfc import jwt as jose_jwt
from joserfc.errors import JoseError
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from ..shared.client_ip import client_ip_from_request, resolve_client_ip
from ..shared.credentials import compare_credential
from ..shared.security_logger import security_logger
from . import pages

if TYPE_CHECKING:
    from .settings import AuthSettings
    from .store import McpUserStore

log = logging.getLogger(__name__)

SCOPE_USER = "fpd:user"
SCOPE_ADMIN = "fpd:admin"

# Per-service HKDF salt: MUST be unique per MCP server so a JWT minted by one
# suite member can never validate at another, even with a shared secret.
_JWT_KEY_SALT = "fpd-mcp-oauth-v1"

_TXN_TTL_SECONDS = 15 * 60

#: L-7: hard cap on in-flight login transactions, independent of the TTL. A
#: caller starting them faster than they expire cannot grow the map forever.
_MAX_IN_FLIGHT_TXNS = 500

#: M-5: cap on the read-through OAuth client cache. Backed by the DB, so an
#: eviction costs one query and never a wrong answer.
_MAX_CACHED_CLIENTS = 500

# H-1 / open Dynamic Client Registration: DCR has to stay on (claude.ai and
# every other MCP client self-registers), but an arbitrary redirect_uri on a
# registered client is the first half of an identity-takeover chain — the
# attacker registers a client pointing at their own host, sends the victim a
# crafted sign-in link, and receives an authorization code for the victim's
# identity. Registration is therefore allowed only for hosts a real MCP client
# actually redirects to. Subdomains of a listed host are accepted. Extend with
# FPD_AUTH_ALLOWED_REDIRECT_HOSTS (comma-separated); set
# FPD_AUTH_OPEN_REGISTRATION=true to restore the previous open behavior.
# Clients already in oauth_clients are unaffected; this gates new registrations
# only, so no connector in use today is disturbed.
_DEFAULT_REDIRECT_HOSTS = frozenset(
    {
        "claude.ai",
        "claude.com",
        "anthropic.com",
        "chatgpt.com",
        "openai.com",
        "localhost",
        "127.0.0.1",
        "::1",
    }
)

# Cookie binding the in-flight login transaction to the browser that is
# actually signing in, checked at the IdP callback.
_TXN_COOKIE = "fpd_txn"
_CODE_TTL_SECONDS = 5 * 60
_JWKS_TTL_SECONDS = 6 * 60 * 60
_HTTP_TIMEOUT = 15.0

# L5: per-IP fixed-window limiter on the OAuth HTTP surface (/authorize,
# /token, /auth/callback). Ported from Citations' auth/provider.py — a
# small, self-contained limiter scoped to this OAuth surface only (not the
# USPTO-outbound rate_limiter, which has different semantics).
_OAUTH_RATE_LIMIT_MAX_REQUESTS = 30
_OAUTH_RATE_LIMIT_WINDOW_SECONDS = 60.0


class _FixedWindowRateLimiter:
    """Minimal per-key fixed-window limiter (dependency-free, process-local)."""

    def __init__(
        self,
        max_requests: int = _OAUTH_RATE_LIMIT_MAX_REQUESTS,
        window_seconds: float = _OAUTH_RATE_LIMIT_WINDOW_SECONDS,
    ) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            window_start, count = self._buckets.get(key, (now, 0))
            if now - window_start >= self._window_seconds:
                window_start, count = now, 0
            count += 1
            self._buckets[key] = (window_start, count)
            return count <= self._max_requests


class _RateLimitedASGIApp:
    """Wraps an ASGI app with a per-client-IP rate limiter (L5).

    Used to guard the framework-provided /authorize and /token routes, whose
    handlers we don't own directly (they come from the MCP SDK's
    create_auth_routes()) — wrapping the route's ASGI app is the one place
    we can intercept every request regardless of handler shape.
    """

    def __init__(self, app, limiter: _FixedWindowRateLimiter) -> None:
        self._app = app
        self._limiter = limiter

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        client = scope.get("client")
        # M-1: honor X-Forwarded-For only from a declared trusted proxy.
        forwarded = dict(scope.get("headers") or {}).get(b"x-forwarded-for")
        ip = resolve_client_ip(
            client[0] if client else None,
            forwarded.decode("latin-1") if forwarded else None,
        )
        if not self._limiter.allow(ip):
            # M-23: the OAuth surface's rate-limit rejections produced no
            # security-log record at all, on either limiter.
            security_logger.log_rate_limit_exceeded(
                client_ip=ip,
                endpoint=scope.get("path", "oauth"),
                current_rate=self._limiter._max_requests + 1,
                limit=self._limiter._max_requests,
                window_seconds=int(self._limiter._window_seconds),
            )
            response = JSONResponse(
                {"error": "too_many_requests", "error_description": "Rate limit exceeded"},
                status_code=429,
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)


# Upstream IdP wiring. Microsoft endpoints are formatted with the configured
# tenant ("organizations", "common", or a tenant GUID).
_GOOGLE_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
_GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
_MS_AUTHORIZE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
_MS_TOKEN = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_MS_JWKS = "https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys"


class FpdAuthorizationCode(AuthorizationCode):
    """Authorization code enriched with the verified upstream identity."""

    email: str = ""
    idp: str = ""
    display_name: str | None = None
    role: str = "user"


class FpdRefreshToken(RefreshToken):
    """Refresh token carrying the user identity for re-authorization."""

    email: str = ""


def scopes_for_role(role: str) -> list[str]:
    return [SCOPE_USER, SCOPE_ADMIN] if role == "admin" else [SCOPE_USER]


def _mask_email(email: str) -> str:
    """Mask a local part for logs, e.g. jane@firm.com -> j***@firm.com."""
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if len(local) <= 1:
        return f"*@{domain}"
    return f"{local[0]}***@{domain}"


class FpdAuthProvider(OAuthProvider):
    def __init__(self, settings: AuthSettings, users: McpUserStore) -> None:
        base_url = settings.auth_base_url.rstrip("/")
        super().__init__(
            base_url=base_url,
            required_scopes=[SCOPE_USER],
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=[SCOPE_USER, SCOPE_ADMIN],
                default_scopes=[SCOPE_USER],
            ),
            revocation_options=RevocationOptions(enabled=True),
        )
        self._settings = settings
        self._users = users
        self._internal_token = settings.auth_internal_token
        # M1: a separate, optional admin-scoped internal bearer — the plain
        # internal token now grants only fpd:user (see load_access_token).
        self._internal_admin_token = settings.auth_internal_admin_token
        self._register_url = settings.auth_register_url
        self._open_registration = (
            os.getenv("FPD_AUTH_OPEN_REGISTRATION", "false").lower() == "true"
        )
        self._allowed_redirect_hosts = _DEFAULT_REDIRECT_HOSTS | {
            host.strip().lower()
            for host in os.getenv(
                "FPD_AUTH_ALLOWED_REDIRECT_HOSTS", ""
            ).split(",")
            if host.strip()
        }
        self._access_ttl = settings.auth_access_ttl
        self._refresh_ttl = settings.auth_refresh_ttl
        self._oauth_rate_limiter = _FixedWindowRateLimiter()
        # Tokens are audience-bound to the MCP resource URL; the transport
        # mounts the MCP endpoint at /mcp.
        self._audience = f"{base_url}/mcp"
        self._issuer = JWTIssuer(
            issuer=base_url,
            audience=self._audience,
            signing_key=derive_jwt_key(
                high_entropy_material=settings.auth_jwt_secret,
                salt=_JWT_KEY_SALT,
            ),
        )
        # In-flight login transactions (txn_id -> parked client request).
        self._txns: dict[str, dict[str, Any]] = {}
        # Registered-client cache in front of the oauth_clients table.
        # M-5: an unbounded dict fed by whatever client_ids arrive. Bounded
        # LRU-by-insertion: it is a read-through cache over the DB, so an
        # eviction costs one query, never a wrong answer.
        self._client_cache: "OrderedDict[str, OAuthClientInformationFull]" = OrderedDict()
        # Cached upstream JWKS: idp -> (fetched_at, KeySet).
        self._jwks: dict[str, tuple[float, jwk.KeySet]] = {}

        tenant = settings.auth_ms_tenant
        self._idps: dict[str, dict[str, str]] = {}
        if settings.auth_google_client_id:
            self._idps["google"] = {
                "authorize": _GOOGLE_AUTHORIZE,
                "token": _GOOGLE_TOKEN,
                "jwks": _GOOGLE_JWKS,
                "client_id": settings.auth_google_client_id,
                "client_secret": settings.auth_google_client_secret,
            }
        if settings.auth_ms_client_id:
            self._idps["microsoft"] = {
                "authorize": _MS_AUTHORIZE.format(tenant=tenant),
                "token": _MS_TOKEN.format(tenant=tenant),
                "jwks": _MS_JWKS.format(tenant=tenant),
                "client_id": settings.auth_ms_client_id,
                "client_secret": settings.auth_ms_client_secret,
            }
        if not self._idps:
            raise ValueError(
                "FPD_AUTH_MODE=oauth requires at least one IdP: set "
                "FPD_AUTH_GOOGLE_CLIENT_ID and/or FPD_AUTH_MS_CLIENT_ID"
            )

    # ------------------------------------------------------------ MCP clients

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        cached = self._client_cache.get(client_id)
        if cached is not None:
            return cached
        payload = await self._users.get_client(client_id)
        if payload is None:
            return None
        client = OAuthClientInformationFull.model_validate(payload)
        self._cache_client(client_id, client)
        return client

    def _cache_client(
        self, client_id: str, client: OAuthClientInformationFull
    ) -> None:
        """Insert into the bounded client cache, evicting the oldest entry."""
        self._client_cache.pop(client_id, None)
        self._client_cache[client_id] = client
        while len(self._client_cache) > _MAX_CACHED_CLIENTS:
            self._client_cache.popitem(last=False)

    def _redirect_host_allowed(self, uri: str) -> bool:
        host = (urlparse(uri).hostname or "").lower()
        if not host:
            return False
        return any(
            host == allowed or host.endswith("." + allowed)
            for allowed in self._allowed_redirect_hosts
        )

    def _reject_unapproved_redirect_uris(
        self, client_info: OAuthClientInformationFull
    ) -> None:
        """Refuse DCR for a client whose redirect_uri host is not approved."""
        if self._open_registration:
            return
        for uri in client_info.redirect_uris or []:
            if not self._redirect_host_allowed(str(uri)):
                log.warning(
                    "OAuth client registration refused: redirect_uri host is not "
                    "in the allowlist (client_name=%s)",
                    client_info.client_name,
                )
                raise RegistrationError(
                    error="invalid_redirect_uri",
                    error_description=(
                        "redirect_uri host is not permitted by this server"
                    ),
                )

    def _bind_txn(self, response: Response, txn_id: str) -> Response:
        """Bind an in-flight login transaction to this browser.

        The IdP callback refuses a transaction whose cookie is absent or does
        not match, so a captured txn id cannot be redeemed from a different
        browser. SameSite=Lax still travels on the top-level GET navigation
        back from Google or Entra.
        """
        txn = self._txns.get(txn_id)
        if txn is None:
            return response
        response.set_cookie(
            _TXN_COOKIE,
            txn["binding"],
            max_age=_TXN_TTL_SECONDS,
            path="/auth",
            httponly=True,
            secure=str(self.base_url).startswith("https"),
            samesite="lax",
        )
        return response

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        assert client_info.client_id is not None
        self._reject_unapproved_redirect_uris(client_info)
        await self._users.put_client(
            client_info.client_id, client_info.model_dump(mode="json")
        )
        self._cache_client(client_info.client_id, client_info)
        # Every dynamic registration leaves a record; there was none before.
        log.info(
            "OAuth client registered: %s (%d redirect uri(s))",
            client_info.client_id,
            len(client_info.redirect_uris or []),
        )

    # ------------------------------------------------------- authorize (step 1)

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Park the client's request and send the browser to the IdP chooser."""
        self._prune_txns()
        txn_id = secrets.token_urlsafe(32)
        self._txns[txn_id] = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "client_state": params.state or "",
            "code_challenge": params.code_challenge,
            "resource": getattr(params, "resource", None),
            "created_at": time.time(),
            "nonce": secrets.token_urlsafe(16),
            "binding": secrets.token_urlsafe(16),
        }
        if len(self._idps) == 1:
            # Single configured IdP: skip the chooser, but still route through
            # /auth/start so the transaction can be bound to this browser
            # before the hop to the IdP. One extra 302, no UX change.
            only = next(iter(self._idps))
            return (
                f"{self.base_url}".rstrip("/") + f"/auth/start/{only}?txn={txn_id}"
            )
        return f"{self.base_url}".rstrip("/") + f"/auth/select?txn={txn_id}"

    def _prune_txns(self) -> None:
        """Drop expired login transactions, and cap the map.

        L-7: pruning happened only inside authorize(), by TTL, with no cap.
        A caller starting transactions faster than they expire grew the map
        without bound; every entry is small, but nothing stopped it.
        """
        cutoff = time.time() - _TXN_TTL_SECONDS
        stale = [k for k, v in self._txns.items() if v["created_at"] < cutoff]
        for k in stale:
            del self._txns[k]
        overflow = len(self._txns) - _MAX_IN_FLIGHT_TXNS
        if overflow > 0:
            oldest = sorted(
                self._txns.items(), key=lambda kv: kv[1]["created_at"]
            )[:overflow]
            for k, _ in oldest:
                del self._txns[k]
            log.warning(
                "Dropped %d oldest in-flight login transaction(s): the cap of "
                "%d was reached", overflow, _MAX_IN_FLIGHT_TXNS,
            )

    def _upstream_authorize_url(self, idp: str, txn_id: str) -> str:
        conf = self._idps[idp]
        txn = self._txns[txn_id]
        params = {
            "client_id": conf["client_id"],
            "redirect_uri": f"{str(self.base_url).rstrip('/')}/auth/callback/{idp}",
            "response_type": "code",
            "scope": "openid email profile",
            "state": txn_id,
            "nonce": txn["nonce"],
        }
        if idp == "google":
            # Always show the account picker; a firm user may have several.
            params["prompt"] = "select_account"
        return f"{conf['authorize']}?{urlencode(params)}"

    # --------------------------------------------------- chooser + IdP callback

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = super().get_routes(mcp_path)
        # L5: rate-limit the framework-provided /authorize and /token routes
        # by wrapping their ASGI app in place — we don't own their handlers
        # (they come from the MCP SDK's create_auth_routes()).
        for route in routes:
            # M-5: /register was NOT in this list, so dynamic client
            # registration — the one route that writes a row per call — was
            # the only unrated OAuth endpoint.
            if getattr(route, "path", None) in ("/authorize", "/token", "/register"):
                route.app = _RateLimitedASGIApp(route.app, self._oauth_rate_limiter)
        routes.extend(
            [
                Route("/auth/select", self._select_endpoint, methods=["GET"]),
                Route("/auth/start/{idp}", self._start_endpoint, methods=["GET"]),
                Route(
                    "/auth/callback/{idp}", self._callback_endpoint, methods=["GET"]
                ),
            ]
        )
        return routes

    async def _select_endpoint(self, request: Request) -> Response:
        txn_id = request.query_params.get("txn", "")
        if txn_id not in self._txns:
            return HTMLResponse(
                pages.error_page(
                    "Sign-in expired",
                    "This sign-in link has expired. Start again from your "
                    "MCP client.",
                ),
                status_code=400,
            )
        return self._bind_txn(HTMLResponse(pages.select_page(txn_id)), txn_id)

    async def _start_endpoint(self, request: Request) -> Response:
        idp = request.path_params["idp"]
        txn_id = request.query_params.get("txn", "")
        if idp not in self._idps or txn_id not in self._txns:
            return HTMLResponse(
                pages.error_page(
                    "Sign-in expired",
                    "This sign-in link has expired. Start again from your "
                    "MCP client.",
                ),
                status_code=400,
            )
        return self._bind_txn(
            RedirectResponse(self._upstream_authorize_url(idp, txn_id), 302),
            txn_id,
        )

    async def _callback_endpoint(self, request: Request) -> Response:
        # L5: /auth/callback isn't a framework route we can wrap in
        # get_routes(), so it's rate-limited inline here.
        # M-1: the resolved client address, not the raw peer — behind a
        # reverse proxy the peer is one value for the whole internet, so this
        # limiter throttled every caller as if they were one.
        ip = client_ip_from_request(request)
        if not self._oauth_rate_limiter.allow(ip):
            security_logger.log_rate_limit_exceeded(
                client_ip=ip,
                endpoint=f"/auth/callback/{request.path_params.get('idp', '')}",
                current_rate=_OAUTH_RATE_LIMIT_MAX_REQUESTS + 1,
                limit=_OAUTH_RATE_LIMIT_MAX_REQUESTS,
                window_seconds=int(_OAUTH_RATE_LIMIT_WINDOW_SECONDS),
            )
            return JSONResponse(
                {"error": "too_many_requests", "error_description": "Rate limit exceeded"},
                status_code=429,
            )

        idp = request.path_params["idp"]
        txn_id = request.query_params.get("state", "")
        code = request.query_params.get("code", "")
        upstream_error = request.query_params.get("error", "")

        txn = self._txns.pop(txn_id, None)
        if idp not in self._idps or txn is None:
            return HTMLResponse(
                pages.error_page(
                    "Sign-in expired",
                    "This sign-in attempt is no longer valid. Start again "
                    "from your MCP client.",
                ),
                status_code=400,
            )
        if request.cookies.get(_TXN_COOKIE) != txn.get("binding"):
            # The transaction was started in a different browser, so this
            # callback is not the sign-in it claims to be. Fail closed.
            log.warning(
                "OAuth callback rejected: login transaction is not bound to "
                "this browser (idp=%s)",
                idp,
            )
            return HTMLResponse(
                pages.error_page(
                    "Sign-in expired",
                    "This sign-in did not start in this browser. Start again "
                    "from your MCP client.",
                ),
                status_code=400,
            )
        if upstream_error or not code:
            log.info("OAuth callback error from %s: %s", idp, upstream_error)
            return HTMLResponse(
                pages.error_page(
                    "Sign-in failed",
                    "The identity provider reported an error "
                    f"({upstream_error or 'no authorization code returned'}). "
                    "Start again from your MCP client.",
                ),
                status_code=400,
            )

        try:
            claims = await self._exchange_and_verify(idp, code, txn["nonce"])
        except Exception as exc:  # noqa: BLE001 — terminal page, log the cause
            log.warning("OAuth %s id_token verification failed: %s", idp, exc)
            return HTMLResponse(
                pages.error_page(
                    "Sign-in failed",
                    "Your login could not be verified with the identity "
                    "provider. Start again from your MCP client.",
                ),
                status_code=400,
            )

        email = self._email_from_claims(idp, claims)
        if not email:
            return HTMLResponse(
                pages.error_page(
                    "Sign-in failed",
                    "The identity provider did not return a usable email "
                    "address for this account.",
                ),
                status_code=400,
            )

        user = await self._users.get_user(email)
        if user is None or not user["active"]:
            log.info("OAuth login rejected (not registered): %s via %s", email, idp)
            return HTMLResponse(
                pages.error_page(
                    "Not registered",
                    f"{email} signed in successfully but is not a registered "
                    "user of this service.",
                    register_url=self._register_url,
                ),
                status_code=403,
            )

        await self._users.record_login(email, idp)
        scopes = scopes_for_role(user["role"])
        display_name = claims.get("name") or user.get("display_name")

        our_code = secrets.token_urlsafe(32)
        await self._users.put_code(
            our_code,
            {
                "client_id": txn["client_id"],
                "redirect_uri": txn["redirect_uri"],
                "redirect_uri_provided_explicitly": txn[
                    "redirect_uri_provided_explicitly"
                ],
                "code_challenge": txn["code_challenge"],
                "resource": txn["resource"],
                "scopes": scopes,
                "email": email,
                "idp": idp,
                "display_name": display_name,
                "role": user["role"],
            },
            ttl_seconds=_CODE_TTL_SECONDS,
        )
        log.info("OAuth login authorized: %s via %s scopes=%s", email, idp, scopes)
        response = RedirectResponse(
            construct_redirect_uri(
                txn["redirect_uri"], code=our_code, state=txn["client_state"] or None
            ),
            302,
        )
        response.delete_cookie(_TXN_COOKIE, path="/auth")
        return response

    async def _exchange_and_verify(
        self, idp: str, code: str, nonce: str
    ) -> dict[str, Any]:
        """Exchange the upstream code and verify the returned id_token."""
        conf = self._idps[idp]
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                conf["token"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": (
                        f"{str(self.base_url).rstrip('/')}/auth/callback/{idp}"
                    ),
                    "client_id": conf["client_id"],
                    "client_secret": conf["client_secret"],
                },
                headers={"Accept": "application/json"},
            )
        if resp.status_code != 200:
            raise ValueError(
                f"upstream token endpoint returned {resp.status_code}: "
                f"{resp.text[:200]}"
            )
        id_token = resp.json().get("id_token")
        if not id_token:
            raise ValueError("upstream token response contained no id_token")

        keyset = await self._get_jwks(idp)
        try:
            decoded = jose_jwt.decode(id_token, keyset, algorithms=["RS256"])
        except (JoseError, ValueError):
            # Key rotation: refetch JWKS once and retry.
            keyset = await self._get_jwks(idp, force=True)
            decoded = jose_jwt.decode(id_token, keyset, algorithms=["RS256"])
        claims: dict[str, Any] = dict(decoded.claims)

        if claims.get("aud") != conf["client_id"]:
            raise ValueError("id_token audience mismatch")
        exp = claims.get("exp")
        if not isinstance(exp, (int, float)) or exp < time.time():
            raise ValueError("id_token expired")
        if claims.get("nonce") != nonce:
            raise ValueError("id_token nonce mismatch")
        if idp == "google":
            self._verify_google_claims(claims)
        else:
            self._verify_entra_claims(claims)
        return claims

    @staticmethod
    def _verify_google_claims(claims: dict[str, Any]) -> None:
        """Validate Google-specific id_token claims: issuer + verified email."""
        iss = claims.get("iss", "")
        if iss not in _GOOGLE_ISSUERS:
            raise ValueError(f"unexpected Google issuer {iss!r}")
        if claims.get("email_verified") is not True:
            raise ValueError("Google account email is not verified")

    def _verify_entra_claims(self, claims: dict[str, Any]) -> None:
        """Validate Entra-specific id_token claims: multi-tenant issuer shape
        (iss embeds the caller's tenant id) plus the configured tenant allowlist."""
        iss = claims.get("iss", "")
        tid = claims.get("tid", "")
        if not tid or iss != f"https://login.microsoftonline.com/{tid}/v2.0":
            raise ValueError(f"unexpected Entra issuer {iss!r}")
        tenant = self._settings.auth_ms_tenant
        if tenant not in ("organizations", "common") and tid != tenant:
            raise ValueError(f"tenant {tid!r} not allowed")

    async def _get_jwks(self, idp: str, force: bool = False) -> jwk.KeySet:
        cached = self._jwks.get(idp)
        if cached and not force and time.time() - cached[0] < _JWKS_TTL_SECONDS:
            return cached[1]
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(self._idps[idp]["jwks"])
        resp.raise_for_status()
        keyset = jwk.KeySet.import_key_set(resp.json())
        self._jwks[idp] = (time.time(), keyset)
        return keyset

    @staticmethod
    def _email_from_claims(idp: str, claims: dict[str, Any]) -> str:
        email = claims.get("email") or ""
        if not email and idp == "microsoft":
            # Entra work accounts frequently omit the optional email claim;
            # preferred_username is the UPN, which is the address firms
            # register with. Only accept it when it is address-shaped.
            candidate = claims.get("preferred_username") or ""
            if "@" in candidate:
                email = candidate
        return email.strip().lower()

    # ------------------------------------------------------ code -> our tokens

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> FpdAuthorizationCode | None:
        payload = await self._users.take_code(authorization_code)
        if payload is None or payload["client_id"] != client.client_id:
            return None
        return FpdAuthorizationCode(
            code=authorization_code,
            scopes=payload["scopes"],
            expires_at=time.time() + _CODE_TTL_SECONDS,
            client_id=payload["client_id"],
            code_challenge=payload["code_challenge"],
            redirect_uri=payload["redirect_uri"],
            redirect_uri_provided_explicitly=payload[
                "redirect_uri_provided_explicitly"
            ],
            resource=payload.get("resource"),
            subject=payload["email"],
            email=payload["email"],
            idp=payload["idp"],
            display_name=payload.get("display_name"),
            role=payload.get("role", "user"),
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        assert isinstance(authorization_code, FpdAuthorizationCode)
        return await self._issue_tokens(
            client_id=authorization_code.client_id,
            email=authorization_code.email,
            scopes=authorization_code.scopes,
            idp=authorization_code.idp,
            display_name=authorization_code.display_name,
            role=authorization_code.role,
        )

    async def _issue_tokens(
        self,
        *,
        client_id: str,
        email: str,
        scopes: list[str],
        idp: str,
        display_name: str | None,
        role: str,
    ) -> OAuthToken:
        access = self._issuer.issue_access_token(
            client_id=client_id,
            scopes=scopes,
            jti=secrets.token_urlsafe(16),
            expires_in=self._access_ttl,
            upstream_claims={
                "email": email,
                "name": display_name,
                "idp": idp,
                "role": role,
            },
        )
        refresh = secrets.token_urlsafe(48)
        await self._users.put_refresh(
            refresh,
            client_id=client_id,
            email=email,
            scopes=scopes,
            ttl_seconds=self._refresh_ttl,
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=self._access_ttl,
            scope=" ".join(scopes),
            refresh_token=refresh,
        )

    # ------------------------------------------------------------ refresh flow

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> FpdRefreshToken | None:
        row = await self._users.get_refresh(refresh_token)
        if row is None:
            # L3: replay of a spent (rotated/revoked) token is an incident,
            # not a silent miss — revoke the whole family for that identity
            # instead of just rejecting this one presentation.
            spent = await self._users.get_refresh_any(refresh_token)
            if spent is not None and spent["revoked"]:
                revoked = await self._users.revoke_all_refresh_for(
                    spent["client_id"], spent["email"]
                )
                security_logger.log_suspicious_activity(
                    activity_description="refresh_token_replay",
                    client_ip="oauth-refresh",
                    indicators={
                        "email": _mask_email(spent["email"]),
                        "client_id": spent["client_id"],
                        "revoked_family_size": revoked,
                    },
                    risk_score=90,
                )
            return None
        if row["client_id"] != client.client_id:
            return None
        return FpdRefreshToken(
            token=refresh_token,
            client_id=row["client_id"],
            scopes=list(row["scopes"]),
            expires_at=int(row["expires_at"].timestamp()),
            subject=row["email"],
            email=row["email"],
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        assert isinstance(refresh_token, FpdRefreshToken)
        # Rotate first: the presented token is spent whatever happens next.
        await self._users.revoke_refresh(refresh_token.token)
        # Re-check the user list so deactivation/demotion takes effect at the
        # next refresh, not at token expiry a month out.
        user = await self._users.get_user(refresh_token.email)
        if user is None or not user["active"]:
            raise TokenError("invalid_grant", "user is no longer authorized")
        fresh_scopes = scopes_for_role(user["role"])
        if scopes:
            requested = set(scopes)
            fresh_scopes = [s for s in fresh_scopes if s in requested] or [SCOPE_USER]
        return await self._issue_tokens(
            client_id=refresh_token.client_id,
            email=refresh_token.email,
            scopes=fresh_scopes,
            idp=user.get("last_login_idp") or "unknown",
            display_name=user.get("display_name"),
            role=user["role"],
        )

    # -------------------------------------------------------- bearer validation

    async def load_access_token(self, token: str) -> AccessToken | None:
        # M1: the admin-scoped internal bearer is a SEPARATE, optional
        # secret — only holders of FPD_AUTH_INTERNAL_ADMIN_TOKEN get
        # fpd:admin. Checked first since it's the more privileged match.
        # L-1: a non-ASCII bearer used to raise TypeError inside
        # compare_digest, so a malformed Authorization header answered 500
        # rather than 401.
        if compare_credential(token, self._internal_admin_token):
            return AccessToken(
                token=token,
                client_id="internal-admin",
                scopes=[SCOPE_USER, SCOPE_ADMIN],
                expires_at=int(time.time()) + self._access_ttl,
                subject="internal-admin",
            )
        # Static internal bearer for headless clients (internal gateways/Claude
        # Code). fpd:user only — no longer full scopes (M1). Constant-time
        # compare.
        if compare_credential(token, self._internal_token):
            return AccessToken(
                token=token,
                client_id="internal",
                scopes=[SCOPE_USER],
                expires_at=int(time.time()) + self._access_ttl,
                subject="internal",
            )
        try:
            payload = self._issuer.verify_token(token)
        except JoseError:
            return None
        except Exception:  # noqa: BLE001 — malformed input must read as 401
            return None
        upstream: dict[str, Any] = payload.get("upstream_claims") or {}
        return AccessToken(
            token=token,
            client_id=payload.get("client_id", ""),
            scopes=(payload.get("scope") or "").split(),
            expires_at=payload.get("exp"),
            subject=upstream.get("email"),
            claims=upstream,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, FpdRefreshToken):
            await self._users.revoke_refresh(token.token)
        # Access tokens are stateless JWTs: they expire on their own (TTL is
        # short); refresh rotation is the revocation lever.


def build_auth_provider(
    settings: AuthSettings, users: McpUserStore
) -> FpdAuthProvider:
    """Validate settings and construct the provider (oauth mode only)."""
    if not settings.auth_base_url.startswith("https://") and not (
        settings.auth_base_url.startswith("http://localhost")
        or settings.auth_base_url.startswith("http://127.0.0.1")
    ):
        raise ValueError(
            "FPD_AUTH_BASE_URL must be the public https:// origin "
            "(or http://localhost for testing)"
        )
    if len(settings.auth_jwt_secret) < 32:
        raise ValueError(
            "FPD_AUTH_JWT_SECRET must be a random string of at least 32 "
            "characters (e.g. `openssl rand -hex 32`)"
        )
    return FpdAuthProvider(settings, users)
