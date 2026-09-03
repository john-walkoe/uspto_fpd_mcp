"""Production genericization is a status-code decision, and prose is not
load-bearing.

F-E7 / F-X4 (error-handling-resilience, exception-flow-analysis):
`_generic_message_for_production` had two keyword branches at the bottom of
its ladder that tested substrings of the PRE-sanitization message at any
status code. A USPTO 400 whose body named a field called "key" came back as
"Configuration error"; anything containing "timeout" read as an outage even on
a 404. Separately, `tools/petitions.py::_no_matches_to_empty` recognizes an
empty USPTO result set from the 404 message, so a 404 branch in that ladder
would turn every empty search into an error in production only, with no test
failing. Both are pinned here.
"""

import pytest

from fpd_mcp.shared.error_utils import format_error_response
from fpd_mcp.tools.petitions import _NO_MATCH_MARKER, _no_matches_to_empty


@pytest.fixture(autouse=True)
def _production_environment(monkeypatch):
    """format_error_response reads ENVIRONMENT; unset means production."""
    monkeypatch.delenv("ENVIRONMENT", raising=False)


def test_a_400_mentioning_a_key_field_is_not_reported_as_a_config_error():
    result = format_error_response(
        "USPTO rejected the query: unknown field 'apiKeyholderName'", 400
    )

    assert result["status_code"] == 400
    assert result["error"] != "Configuration error"
    assert "apiKeyholderName" in result["error"]


def test_a_404_mentioning_a_timeout_is_not_reported_as_an_outage():
    result = format_error_response(
        "No matching records found for petitionTimeoutCode", 404
    )

    assert result["status_code"] == 404
    assert result["error"] != "Service temporarily unavailable"


@pytest.mark.parametrize(
    "status_code,expected",
    [
        (401, "Authentication required"),
        (403, "Access denied"),
        (429, "Rate limit exceeded"),
        (500, "Internal server error occurred"),
        (503, "Internal server error occurred"),
    ],
)
def test_status_code_overrides_are_unchanged(status_code, expected):
    result = format_error_response("upstream detail", status_code)

    assert result["error"] == expected


def test_authored_recovery_text_survives_genericization():
    """A server-written 503 must reach the model as written, not as
    "Internal server error occurred" — the message IS the recovery advice."""
    result = format_error_response(
        "Document metadata is temporarily unavailable for this petition. "
        "Retry later.",
        503,
        authored=True,
    )

    assert result["status_code"] == 503
    assert "Retry later" in result["error"]


def test_an_empty_search_survives_the_production_error_envelope():
    """F-X4: the 404-to-empty mapping runs on the REAL envelope, not a
    hand-built dict, so a future 404 branch in the genericization ladder
    fails here instead of shipping."""
    envelope = format_error_response(
        f"API error: {_NO_MATCH_MARKER}", 404, "req-1"
    )

    result = _no_matches_to_empty(envelope)

    assert result["count"] == 0
    assert "error" not in result


# --------------------------------------------------------------------- F-E8


@pytest.mark.parametrize("environment", ["development", "dev", "test"])
def test_the_detail_branch_is_reachable_and_covered(monkeypatch, environment):
    """F-E8: ENVIRONMENT appeared nowhere in .env.example, the Dockerfile or
    deploy/, so `include_details` was False in production (correct) AND for
    every developer and every test run — a debug mode the repo carried and
    maintained that nobody could turn on without reading the source. It is
    documented now; this covers the branch."""
    monkeypatch.setenv("ENVIRONMENT", environment)

    result = format_error_response(
        "upstream said something specific", 500, "req-1",
        context={"endpoint": "search"},
    )

    assert result["error"] == "upstream said something specific"
    assert result["context"] == {"endpoint": "search"}


def test_production_never_emits_the_context_block(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")

    result = format_error_response(
        "upstream detail", 500, "req-1", context={"endpoint": "search"}
    )

    assert "context" not in result
    assert result["error"] == "Internal server error occurred"
