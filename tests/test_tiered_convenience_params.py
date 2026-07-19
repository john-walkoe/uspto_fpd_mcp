"""
Tests for the tiered convenience parameters implementation in FPD MCP.

Phase 6A item 5: this file previously re-implemented ~140 lines of main.py's
_build_convenience_query / validate_string_param / validate_date_range /
validate_application_number logic as local copies — a drifted fork that had
silently diverged from the production implementation (most importantly, the
fork raised bare `ValueError` and validated strings against a DENYLIST,
while production raises `fpd_mcp.shared.error_utils.ValidationError` and
validates strings against an ALLOWLIST — see "DRIFT CORRECTIONS" below).

Every test in this file now imports and exercises the REAL functions from
fpd_mcp.main (and, after Phase 6A item 2's decomposition, the real
_apply_minimal_params / _apply_balanced_params / _reject_balanced_only_params
/ _apply_date_range_param helpers _build_convenience_query is now a thin
orchestrator over), so this suite locks the decomposed implementation
instead of a hand-maintained copy of it.

DRIFT CORRECTIONS found while rewriting (fork behavior -> real behavior):
1. Exception type: fork raised plain `ValueError` from its local
   validate_date_range / validate_string_param / validate_application_number
   / _build_convenience_query. Production raises
   `fpd_mcp.shared.error_utils.ValidationError` (NOT a ValueError subclass —
   it inherits directly from Exception via FPDException). A caller doing
   `except ValueError` against the real code would NOT catch it. All
   `pytest.raises` in this file now target ValidationError.
2. String validation strategy: the fork's `validate_string_param` rejected
   values matching a DENYLIST (`[<>"'\\/\x00-\x1f]`), which does not
   include Lucene metacharacters (`: ( ) [ ] * ? ~ ^` etc.) — those would
   have passed the fork's check but reach the outbound Lucene query
   unescaped. Production (main.py's M2 hardening) uses an ALLOWLIST
   (`^[\\w\\s.,&'-]+$`) instead: only word characters, whitespace, and the
   punctuation legitimate names/offices actually use (period, comma,
   ampersand, apostrophe, hyphen) are permitted, and Lucene metacharacters
   are rejected outright. This is an outcome-level correction, not just an
   exception-type correction, in both directions:
     a. The fork's denylist REJECTED apostrophes (`\\'` was denylisted), so
        a name like "O'Brien Corp" would have failed fork validation.
        Production's allowlist explicitly PERMITS apostrophes (see
        `TestStringValidation::test_apostrophe_is_allowed`).
     b. The fork's denylist did not reject Lucene metacharacters like `:`,
        so a value such as "Acme:Corp" would have PASSED fork validation
        and reached the query string unescaped. Production's allowlist
        REJECTS it (see `TestStringValidation::test_lucene_metacharacters_rejected`).
   Case 2 has no effect on the pre-existing test scenarios (none of them
   used apostrophes or Lucene metacharacters), so no existing assertion
   needed correcting for it — the two new test cases above capture the
   corrected behavior going forward.
3. Message text: every corrected message (too-long, invalid-characters,
   date-format, date-range, application-number-shape, tier-gating-rejection,
   no-criteria) is byte-identical between the fork and production; only the
   exception class changed. Verified line-by-line against main.py.
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

# main.py's module-level `settings = Settings()` needs a resolvable
# USPTO_API_KEY at import time (same pattern used throughout this test
# suite, e.g. test_security_hardening_phase23.py) — the pure query-building
# / validation helpers under test here never touch the API key themselves.
os.environ.setdefault("USPTO_API_KEY", "x" * 30)

from fpd_mcp.api.field_constants import FPDFields, QueryFieldNames  # noqa: E402
from fpd_mcp.main import (  # noqa: E402
    _apply_balanced_params,
    _apply_date_range_param,
    _apply_minimal_params,
    _build_convenience_query,
    _reject_balanced_only_params,
    validate_application_number,
    validate_date_range,
    validate_string_param,
)
from fpd_mcp.shared.error_utils import ValidationError  # noqa: E402


# =============================================================================
# validate_date_range
# =============================================================================


class TestDateValidation:
    @pytest.mark.parametrize(
        "date_str,expected",
        [
            ("2024-01-01", "2024-01-01"),
            ("2023-12-31", "2023-12-31"),
            ("", None),
            ("   ", None),
            (None, None),
        ],
    )
    def test_valid_and_empty_dates(self, date_str, expected):
        assert validate_date_range(date_str) == expected

    def test_invalid_format_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_date_range("2024/01/01")
        assert "YYYY-MM-DD format" in str(exc_info.value)

    def test_invalid_month_rejected(self):
        with pytest.raises(ValidationError):
            validate_date_range("2024-13-01")

    def test_too_old_date_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_date_range("1980-01-01")
        assert "between 1990 and" in str(exc_info.value)

    def test_too_far_future_date_rejected(self):
        future_year = datetime.now().year + 6
        with pytest.raises(ValidationError) as exc_info:
            validate_date_range(f"{future_year}-01-01")
        assert "between 1990 and" in str(exc_info.value)


# =============================================================================
# validate_string_param
# =============================================================================


class TestStringValidation:
    def test_valid_string_passes_through(self):
        assert validate_string_param("test", "Apple Inc.") == "Apple Inc."

    def test_whitespace_is_trimmed(self):
        assert validate_string_param("test", "  Valid Name  ") == "Valid Name"

    @pytest.mark.parametrize("value", ["", None])
    def test_empty_or_none_returns_none(self, value):
        assert validate_string_param("test", value) is None

    def test_html_like_characters_rejected(self):
        with pytest.raises(ValidationError):
            validate_string_param("test", "Invalid<script>")

    def test_too_long_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_string_param("test", "x" * 201)
        assert "too long" in str(exc_info.value)

    def test_max_length_boundary_is_inclusive(self):
        # 200 chars is exactly the default max_length -> allowed
        assert validate_string_param("test", "x" * 200) == "x" * 200
        with pytest.raises(ValidationError):
            validate_string_param("test", "x" * 201)

    # --- DRIFT CORRECTION 2a: apostrophe is ALLOWED (fork's denylist
    # rejected it; production's M2 allowlist explicitly permits it as
    # punctuation legitimate names use, e.g. "O'Brien").
    def test_apostrophe_is_allowed(self):
        assert validate_string_param("applicant_name", "O'Brien Corp") == "O'Brien Corp"

    # --- DRIFT CORRECTION 2b: Lucene metacharacters are REJECTED (fork's
    # denylist did not cover them, so they would have reached the outbound
    # query string unescaped; production's M2 allowlist rejects them
    # outright).
    @pytest.mark.parametrize(
        "value",
        ["Acme:Corp", "Acme(Corp)", "Acme[Corp]", "Acme*Corp", "Acme?Corp", "Acme^Corp", 'Acme"Corp"'],
    )
    def test_lucene_metacharacters_rejected(self, value):
        with pytest.raises(ValidationError) as exc_info:
            validate_string_param("applicant_name", value)
        assert "invalid characters" in str(exc_info.value)

    @pytest.mark.parametrize(
        "value", ["Johnson & Johnson", "Smith, Jones and Co.", "Multi-Word-Name"]
    )
    def test_allowed_punctuation(self, value):
        assert validate_string_param("test", value) == value


# =============================================================================
# validate_application_number
# =============================================================================


class TestApplicationNumberValidation:
    @pytest.mark.parametrize(
        "app_number,expected",
        [
            ("17896175", "17896175"),
            ("17/896175", "17896175"),
            ("  17 896 175  ", "17896175"),
            ("", None),
            (None, None),
        ],
    )
    def test_valid_and_empty(self, app_number, expected):
        assert validate_application_number(app_number) == expected

    def test_too_short_rejected(self):
        with pytest.raises(ValidationError):
            validate_application_number("12345")

    def test_too_long_rejected(self):
        with pytest.raises(ValidationError):
            validate_application_number("12345678901")

    def test_non_digits_rejected(self):
        with pytest.raises(ValidationError):
            validate_application_number("17ABC175")


# =============================================================================
# _build_convenience_query — minimal tier
# =============================================================================


class TestMinimalQueryBuilding:
    def test_basic_minimal_parameters(self):
        query, params = _build_convenience_query(
            applicant_name="Apple Inc.",
            decision_type="DENIED",
            patent_number="11788453",
            allow_balanced_params=False,
        )

        expected_parts = [
            f'{QueryFieldNames.APPLICANT_NAME}:"Apple Inc."',
            f'{QueryFieldNames.PATENT_NUMBER}:11788453',
            f'{QueryFieldNames.DECISION_TYPE}:DENIED',
        ]
        for part in expected_parts:
            assert part in query, f"Missing query part: {part}"

        assert params["applicant_name"] == "Apple Inc."
        assert params["decision_type"] == "DENIED"
        assert params["patent_number"] == "11788453"

    def test_petition_date_range(self):
        query, params = _build_convenience_query(
            petition_date_start="2024-01-01",
            petition_date_end="2024-12-31",
            allow_balanced_params=False,
        )
        assert f"{QueryFieldNames.PETITION_MAIL_DATE}:[2024-01-01 TO 2024-12-31]" in query
        assert params["petition_date_range"] == "2024-01-01 TO 2024-12-31"

    def test_decision_date_range_open_ended(self):
        query, params = _build_convenience_query(
            decision_date_start="2024-01-01",
            allow_balanced_params=False,
        )
        assert f"{QueryFieldNames.DECISION_DATE}:[2024-01-01 TO *]" in query
        assert params["decision_date_range"] == "2024-01-01 TO *"

    def test_hybrid_query_and_parameters(self):
        query, params = _build_convenience_query(
            query="machine learning",
            applicant_name="TechCorp",
            decision_type="DENIED",
            allow_balanced_params=False,
        )
        assert "(machine learning)" in query
        assert f'{QueryFieldNames.APPLICANT_NAME}:"TechCorp"' in query
        assert f"{QueryFieldNames.DECISION_TYPE}:DENIED" in query
        assert params["base_query"] == "machine learning"
        assert params["applicant_name"] == "TechCorp"

    def test_empty_parameters_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            _build_convenience_query(allow_balanced_params=False)
        assert "Must provide either" in str(exc_info.value)

    def test_application_number_cleaning(self):
        query, params = _build_convenience_query(
            application_number="17/896 175",
            allow_balanced_params=False,
        )
        assert f"{QueryFieldNames.APPLICATION_NUMBER}:17896175" in query
        assert params["application_number"] == "17896175"

    def test_multiple_parameter_combination(self):
        query, params = _build_convenience_query(
            applicant_name="Apple Inc.",
            decision_type="DENIED",
            petition_date_start="2024-01-01",
            petition_date_end="2024-12-31",
            application_number="17896175",
            allow_balanced_params=False,
        )

        # 4 query parts (petition date start/end combine into one range) ->
        # 3 AND operators.
        assert query.count(" AND ") == 3, f"Expected 3 AND operators, got query: {query}"
        assert len(params) == 4

    def test_special_character_handling(self):
        query, _params = _build_convenience_query(
            applicant_name="Tech Corp Inc.",
            allow_balanced_params=False,
        )
        assert f'{QueryFieldNames.APPLICANT_NAME}:"Tech Corp Inc."' in query

        query, _params = _build_convenience_query(
            deciding_office="OFFICE OF PETITIONS",
            allow_balanced_params=False,
        )
        assert f'{FPDFields.FINAL_DECIDING_OFFICE_NAME}:"OFFICE OF PETITIONS"' in query

    def test_balanced_only_param_rejected_in_minimal_tier(self):
        """DRIFT CORRECTION 1: raises ValidationError, not ValueError."""
        with pytest.raises(ValidationError) as exc_info:
            _build_convenience_query(
                applicant_name="Apple Inc.",
                art_unit="2128",  # Balanced only
                allow_balanced_params=False,
            )
        assert "art_unit" in str(exc_info.value)
        assert "fpd_search_petitions_balanced" in str(exc_info.value)


# =============================================================================
# _build_convenience_query — balanced tier
# =============================================================================


class TestBalancedQueryBuilding:
    def test_balanced_parameters(self):
        query, params = _build_convenience_query(
            applicant_name="TechCorp",
            decision_type="DENIED",
            art_unit="2128",
            petition_type_code="551",
            entity_status="Small",
            allow_balanced_params=True,
        )

        expected_parts = [
            f'{QueryFieldNames.APPLICANT_NAME}:"TechCorp"',
            f"{QueryFieldNames.DECISION_TYPE}:DENIED",
            f"{QueryFieldNames.ART_UNIT}:2128",
            f"{FPDFields.DECISION_PETITION_TYPE_CODE}:551",
            f'{QueryFieldNames.BUSINESS_ENTITY}:"Small"',
        ]
        for part in expected_parts:
            assert part in query, f"Missing query part: {part}"

        assert params["applicant_name"] == "TechCorp"
        assert params["art_unit"] == "2128"
        assert params["petition_type_code"] == "551"

    def test_same_parameters_succeed_when_balanced_allowed(self):
        """Same parameters as the minimal-tier rejection test above succeed
        once allow_balanced_params=True (progressive disclosure)."""
        query, _params = _build_convenience_query(
            applicant_name="Apple Inc.",
            art_unit="2128",
            allow_balanced_params=True,
        )
        assert f'{QueryFieldNames.APPLICANT_NAME}:"Apple Inc."' in query
        assert f"{QueryFieldNames.ART_UNIT}:2128" in query

    @pytest.mark.parametrize(
        "kwarg,value",
        [
            ("petition_type_code", "551"),
            ("art_unit", "2128"),
            ("technology_center", "2100"),
            ("prosecution_status", "During examination"),
            ("entity_status", "Small"),
        ],
    )
    def test_each_balanced_only_param_individually_rejected_in_minimal_tier(self, kwarg, value):
        """Table-driven version of the tier-gating check: each of the 5
        balanced-only parameters, alone, is rejected when
        allow_balanced_params=False."""
        with pytest.raises(ValidationError) as exc_info:
            _build_convenience_query(allow_balanced_params=False, **{kwarg: value})
        assert kwarg in str(exc_info.value)
        assert "fpd_search_petitions_balanced" in str(exc_info.value)


# =============================================================================
# Real decomposed helpers (Phase 6A item 2) — exercised directly, since
# _build_convenience_query is now a thin orchestrator over these.
# =============================================================================


class TestApplyDateRangeParamHelper:
    def test_both_bounds(self):
        query_parts, params_used = [], {}
        _apply_date_range_param(
            query_parts, params_used, "petition_date_range",
            QueryFieldNames.PETITION_MAIL_DATE, "2024-01-01", "2024-12-31",
        )
        assert query_parts == [f"{QueryFieldNames.PETITION_MAIL_DATE}:[2024-01-01 TO 2024-12-31]"]
        assert params_used == {"petition_date_range": "2024-01-01 TO 2024-12-31"}

    def test_neither_bound_is_a_noop(self):
        query_parts, params_used = [], {}
        _apply_date_range_param(
            query_parts, params_used, "petition_date_range",
            QueryFieldNames.PETITION_MAIL_DATE, None, None,
        )
        assert query_parts == []
        assert params_used == {}

    def test_invalid_bound_raises_validation_error(self):
        with pytest.raises(ValidationError):
            _apply_date_range_param(
                [], {}, "petition_date_range",
                QueryFieldNames.PETITION_MAIL_DATE, "not-a-date", None,
            )


class TestApplyMinimalParamsHelper:
    def test_populates_query_parts_and_params_in_order(self):
        query_parts, params_used = [], {}
        _apply_minimal_params(
            query_parts, params_used,
            query="", applicant_name="Apple Inc.", application_number=None,
            patent_number=None, decision_type=None, deciding_office=None,
            petition_date_start=None, petition_date_end=None,
            decision_date_start=None, decision_date_end=None,
        )
        assert query_parts == [f'{QueryFieldNames.APPLICANT_NAME}:"Apple Inc."']
        assert params_used == {"applicant_name": "Apple Inc."}


class TestApplyBalancedParamsHelper:
    def test_populates_query_parts_and_params(self):
        query_parts, params_used = [], {}
        _apply_balanced_params(
            query_parts, params_used,
            petition_type_code="551", art_unit=None, technology_center=None,
            prosecution_status=None, entity_status=None,
        )
        assert query_parts == [f"{FPDFields.DECISION_PETITION_TYPE_CODE}:551"]
        assert params_used == {"petition_type_code": "551"}


class TestRejectBalancedOnlyParamsHelper:
    def test_all_none_is_a_noop(self):
        # Should not raise.
        _reject_balanced_only_params(None, None, None, None, None)

    def test_any_provided_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc_info:
            _reject_balanced_only_params("551", None, None, None, None)
        assert "petition_type_code" in str(exc_info.value)
        assert "fpd_search_petitions_balanced" in str(exc_info.value)
