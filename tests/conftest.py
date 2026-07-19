"""Shared pytest fixtures for tool-level tests.

`mock_runtime` patches the two service singletons tool modules look up as
`runtime.<attr>` on every call (the seam documented in runtime.py's module
docstring — `get_api_client()` / `get_fpd_service()` return whatever is
currently bound to the module-level `api_client` / `fpd_service` globals, so
patching those globals directly reaches every tool). It wires:

- `api_client`: an AsyncMock stand-in for FPDClient — the network boundary,
  the same seam tests/test_basic.py and tests/test_integration.py exercise
  for real. Tools that call `get_api_client()` directly (the document tools)
  see this mock.
- `field_manager`: a REAL FieldManager loaded from the project's actual
  field_configs.yaml, so field-filtering behaves exactly as in production
  instead of needing to be hand-mocked.
- `fpd_service`: a REAL FPDService wrapping the mocked `api_client` above, so
  the search/details tool tests exercise real service-layer logic (field
  filtering via FieldManager, error passthrough) over a mocked network
  boundary rather than mocking the service layer itself.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

# Match tests/test_basic.py's sys.path bootstrap so `import fpd_mcp` resolves
# under plain `pytest` invocation without requiring an editable install.
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

from fpd_mcp import runtime  # noqa: E402
from fpd_mcp.config.field_manager import FieldManager  # noqa: E402
from fpd_mcp.services.fpd_service import FPDService  # noqa: E402

_FIELD_CONFIGS_PATH = Path(runtime.__file__).resolve().parent.parent.parent / "field_configs.yaml"


@pytest.fixture
def mock_runtime(monkeypatch):
    """Patch runtime.* with a mocked FPDClient wrapped in a real FPDService.

    Returns a SimpleNamespace with `api_client`, `field_manager`,
    `fpd_service` so tests can configure `.search_petitions.return_value` /
    `.get_petition_by_id.return_value` etc. and assert on `.call_args`.
    """
    api_client = AsyncMock()
    field_manager = FieldManager(_FIELD_CONFIGS_PATH)
    fpd_service = FPDService(api_client, field_manager)

    monkeypatch.setattr(runtime, "api_client", api_client)
    monkeypatch.setattr(runtime, "field_manager", field_manager)
    monkeypatch.setattr(runtime, "fpd_service", fpd_service)

    return SimpleNamespace(
        api_client=api_client,
        field_manager=field_manager,
        fpd_service=fpd_service,
    )
