"""Final Petition Decisions MCP Server

Environment Variables:
    USPTO_API_KEY: Required USPTO API key from https://data.uspto.gov/myodp/
    MISTRAL_API_KEY: Optional Mistral API key for OCR on scanned documents

    Proxy Configuration:
        ENABLE_PROXY_SERVER: Enable/disable proxy functionality (default: true)
        ENABLE_ALWAYS_ON_PROXY: Start proxy immediately vs on-demand (default: true)
        FPD_PROXY_PORT: Local proxy server port (default: 8081)
        CENTRALIZED_PROXY_PORT: Centralized PFW proxy port (auto-detected)

    API Configuration:
        USPTO_TIMEOUT: API request timeout in seconds (default: 30.0)
        USPTO_DOWNLOAD_TIMEOUT: Document download/OCR timeout in seconds (default: 60.0)
"""

# FastMCP 4 / mcp-types 2 dropped extra="allow" on ToolAnnotations, which
# silently strips the `defer_loading` flag off every tool. Must run before any
# tool is registered. See fastmcp_compat for the full rationale. Applied here
# AND at the top of server_app (the composition root), because either module
# can be the first one imported; apply() is idempotent.
from .fastmcp_compat import apply as _apply_fastmcp_compat

_apply_fastmcp_compat()

# Settings/logging/keys and the FPD API client + FPDService singletons live
# in runtime.py; importing it here (before _build_auth_provider is defined
# and called) triggers the settings/logging bootstrap exactly once, at the
# same point in module load order the pre-decomposition main.py did it.
from .runtime import (
    config_path,
    get_api_client,
    get_fpd_service,
    logger,
    settings,
)


# The composed server (instructions, OAuth provider, MCP App resources,
# prompts, tools, title pinning, admin gate) is built in server_app.py.
# F-A1: server_bootstrap.py used to read `main.mcp` / `main._AUTH_PROVIDER`
# through three function-local `from . import main` imports, which made
# main <-> server_bootstrap a real import cycle. Both now depend on
# server_app instead, and server_app.build_server() is the seam for a caller
# that wants the server without this module's re-export surface.
from .server_app import (  # noqa: E402
    ADMIN_GATED_TOOLS,  # noqa: F401
    SERVER_INSTRUCTIONS,  # noqa: F401
    _attach_admin_scope_checks,  # noqa: F401
    _build_auth_provider,  # noqa: F401
    _pin_tool_titles,  # noqa: F401
    build_server,  # noqa: F401
    get_auth_provider,
    get_server,
)

# Bound at import time on purpose: `from fpd_mcp.main import mcp` is the
# documented handle for the tests, the registration-gate subprocesses and
# `python -m fpd_mcp.main`.
mcp = get_server()
_AUTH_PROVIDER = get_auth_provider()

# ---------------------------------------------------------------------------
# Back-compat re-exports (tests + external callers import these from main)
# ---------------------------------------------------------------------------
from .tools.admin import fpd_manage_users  # noqa: E402,F401
from .tools.admin import USER_MANAGEMENT_ENABLED  # noqa: E402,F401
from .tools.petitions import (  # noqa: E402,F401
    fpd_search_petitions_minimal,
    fpd_search_petitions_balanced,
    fpd_search_petitions_by_art_unit,
    fpd_search_petitions_by_application,
    fpd_get_petition_details,
    _apply_minimal_params,
    _apply_balanced_params,
    _apply_date_range_param,
    _reject_balanced_only_params,
    _build_convenience_query,
)
from .tools.documents import (  # noqa: E402,F401
    fpd_get_document_download,
    fpd_get_document_content,
)
from .tools.guidance import fpd_get_guidance  # noqa: E402,F401

from .validators import (  # noqa: E402,F401
    validate_date_range,
    validate_string_param,
    validate_application_number,
    validate_petition_id,
    validate_document_identifier,
)

from .middleware import (  # noqa: E402,F401
    APIKeyAuthMiddleware,
    SecurityHeadersMiddleware,
    _StreamableHTTPProbeMiddleware,
)
from .server_bootstrap import (  # noqa: E402,F401
    _detect_pfw_proxy,
    _ensure_proxy_server_running,
    _on_proxy_task_done,
    get_local_proxy_port,
    handle_async_exception,
    install_async_exception_handler,
    main,
    run_hybrid_server,
    run_server,
)


if __name__ == "__main__":
    main()
