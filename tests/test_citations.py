"""Hermetic tests for `cite_as`: "citations are links".

Every petition decision row leaves this server with a markdown link the model
can paste into an answer. These pin:

- the two verified URL forms (Patent Center, Google Patents) and nothing else,
- which of them a petition row points at,
- the label shape ("Petition decision <date>, application <serial>"),
- the minimal tier's compact form (the same URL as a markdown autolink),
- that the short note rides on the envelope of every petition tool,
- and the hard rule that a download-proxy persistent link is NEVER a citation
  target (a static scan over the source, plus a unit test of the refusal).

No live USPTO calls: every response is a fixture.
"""

import pathlib
import re

from fpd_mcp.shared import citations as shared_citations
from fpd_mcp.tools.petitions import (
    fpd_get_petition_details,
    fpd_search_petitions_balanced,
    fpd_search_petitions_by_application,
    fpd_search_petitions_by_art_unit,
    fpd_search_petitions_minimal,
)
from fpd_mcp.util import citations as fpd_citations

_PETITION_ID = "e55bd36d-961f-511e-b72c-b4b1529d67ef"

#: A granted-patent record: the citation goes to Google Patents.
_GRANTED_ROW = {
    "petitionDecisionRecordIdentifier": _PETITION_ID,
    "applicationNumberText": "12/950,321",
    "patentNumber": "8539047",
    "firstApplicantName": "TechCorp Inc.",
    "decisionTypeCodeDescriptionText": "DENIED",
    "petitionMailDate": "2019-01-04",
    "decisionDate": "2019-06-11",
    "finalDecidingOfficeName": "OFFICE OF PETITIONS",
}

#: A pending-application record: the citation goes to Patent Center. The API
#: OMITS a field it has no value for, so patentNumber is simply absent.
_PENDING_ROW = {
    "petitionDecisionRecordIdentifier": _PETITION_ID,
    "applicationNumberText": "12950321",
    "decisionTypeCodeDescriptionText": "DENIED",
    "decisionDate": "2019-06-11",
}

_PATENT_CENTER_CITE = (
    "[Petition decision 2019-06-11, application 12/950,321]"
    "(https://patentcenter.uspto.gov/applications/12950321)"
)
_GOOGLE_PATENTS_CITE = (
    "[Petition decision 2019-06-11, application 12/950,321]"
    "(https://patents.google.com/patent/US8539047)"
)

#: FPD_Search_petitions_minimal's compact form: the same targets, no label.
_PATENT_CENTER_COMPACT = "<https://patentcenter.uspto.gov/applications/12950321>"
_GOOGLE_PATENTS_COMPACT = "<https://patents.google.com/patent/US8539047>"

_NOTE = fpd_citations.ENVELOPE_CITATION_NOTE


def _bag(*rows, count=None):
    return {
        "petitionDecisionDataBag": [dict(r) for r in rows],
        "count": len(rows) if count is None else count,
    }


# ---------------------------------------------------------------------------
# The shared mechanism
# ---------------------------------------------------------------------------

class TestUrlBuilders:
    def test_patent_center_accepts_the_shapes_uspto_sends(self):
        for value in ("12950321", "12/950,321", "12 950 321"):
            assert (shared_citations.patent_center_url(value)
                    == "https://patentcenter.uspto.gov/applications/12950321")

    def test_patent_center_refuses_what_it_cannot_resolve(self):
        for value in (None, "", "950321", "PCT/US2011/001234"):
            assert shared_citations.patent_center_url(value) is None

    def test_google_patents_accepts_grant_and_publication_numbers(self):
        assert (shared_citations.google_patents_url("8,539,047")
                == "https://patents.google.com/patent/US8539047")
        assert (shared_citations.google_patents_url("20010056539")
                == "https://patents.google.com/patent/US20010056539")
        assert shared_citations.google_patents_url("EP1234567") is None

    def test_display_forms(self):
        assert shared_citations.format_application_display("12950321") == "12/950,321"
        assert shared_citations.format_patent_display("8539047") == "US 8,539,047"

    def test_cite_as_link_refuses_a_delivery_link(self):
        """The persistent-link hash IS the credential (Lesson 43), so it can
        never become a citation, whatever label is handed in."""
        for url in (
            "http://localhost:8081/download/persistent/deadbeef",
            "https://proxy.example.test/document/persistent/deadbeef",
        ):
            assert shared_citations.is_delivery_link(url) is True
            assert shared_citations.cite_as_link("Petition decision", url) is None


# ---------------------------------------------------------------------------
# The petition label + target
# ---------------------------------------------------------------------------

class TestPetitionCiteAs:
    def test_patent_number_wins_the_target(self):
        assert fpd_citations.petition_cite_as(
            "2019-06-11", "12/950,321", "8539047"
        ) == _GOOGLE_PATENTS_CITE

    def test_without_a_patent_it_is_patent_center(self):
        assert fpd_citations.petition_cite_as(
            "2019-06-11", "12950321"
        ) == _PATENT_CENTER_CITE

    def test_a_missing_date_still_produces_a_link(self):
        assert fpd_citations.petition_cite_as(None, "12950321") == (
            "[Petition decision, application 12/950,321]"
            "(https://patentcenter.uspto.gov/applications/12950321)"
        )

    def test_nothing_citable_means_no_link(self):
        assert fpd_citations.petition_cite_as("2019-06-11", None, None) is None

    def test_attach_is_a_no_op_on_an_error_envelope(self):
        envelope = {"error": "boom", "status_code": 500}
        assert fpd_citations.attach_citations(envelope) == {
            "error": "boom", "status_code": 500,
        }

    def test_a_datetime_decision_date_is_trimmed_to_the_day(self):
        result = fpd_citations.attach_citations(
            _bag({**_PENDING_ROW, "decisionDate": "2019-06-11T00:00:00Z"})
        )
        assert result["petitionDecisionDataBag"][0]["cite_as"] == _PATENT_CENTER_CITE


class TestCompactCiteAs:
    """FPD_Search_petitions_minimal's form: the verified URL as a markdown
    autolink. Same targets, same refusal, no label."""

    def test_patent_number_wins_the_target(self):
        assert fpd_citations.compact_petition_cite_as(
            "12/950,321", "8539047"
        ) == _GOOGLE_PATENTS_COMPACT

    def test_without_a_patent_it_is_patent_center(self):
        assert fpd_citations.compact_petition_cite_as("12950321") == _PATENT_CENTER_COMPACT

    def test_nothing_citable_means_no_link(self):
        assert fpd_citations.compact_petition_cite_as(None, None) is None

    def test_a_delivery_link_is_refused(self, monkeypatch):
        monkeypatch.setattr(
            fpd_citations, "_petition_url",
            lambda *_: "http://localhost:8081/download/persistent/deadbeef",
        )
        assert fpd_citations.compact_petition_cite_as("12950321") is None

    def test_attach_compact_on_a_bag(self):
        result = fpd_citations.attach_citations(_bag(_PENDING_ROW), compact=True)
        assert result["petitionDecisionDataBag"][0]["cite_as"] == _PATENT_CENTER_COMPACT
        assert result["citation_note"] == _NOTE


class TestEnvelopeNote:
    """A few sentences on every envelope; the full rules live in
    FPD_get_guidance(section='overview')."""

    def test_it_is_short(self):
        assert len(_NOTE) <= 400
        assert len(_NOTE) < len(shared_citations.CITATION_NOTE) // 2

    def test_it_says_what_to_do(self):
        assert "cite_as" in _NOTE
        assert "patentcenter.uspto.gov" in _NOTE
        assert "free USPTO.gov account" in _NOTE
        assert "download link" in _NOTE
        assert "FPD_get_guidance(section='overview')" in _NOTE
        assert "\u2014" not in _NOTE  # no em dashes in served prose

    def test_the_overview_carries_the_full_rules(self):
        from fpd_mcp.config.tool_reflections import get_guidance_section

        overview = get_guidance_section("overview")
        flat = " ".join(overview.split())
        assert "## CITATIONS ARE LINKS" in overview
        assert (
            "Patent Center shows an application only to a signed-in reader: without a "
            "free USPTO.gov account the link lands on its own front page"
        ) in flat
        assert "markdown autolink" in flat
        assert "FPD_get_document_download" in flat


# ---------------------------------------------------------------------------
# The tools
# ---------------------------------------------------------------------------

class TestSearchToolCitations:
    async def test_minimal_row_and_envelope(self, mock_runtime):
        mock_runtime.api_client.search_petitions.return_value = _bag(_GRANTED_ROW)

        result = await fpd_search_petitions_minimal(applicant_name="TechCorp Inc.")

        assert result["petitionDecisionDataBag"][0]["cite_as"] == _GOOGLE_PATENTS_COMPACT
        assert result["citation_note"] == _NOTE

    async def test_minimal_pending_row_is_the_compact_patent_center_link(self, mock_runtime):
        mock_runtime.api_client.search_petitions.return_value = _bag(_PENDING_ROW)

        result = await fpd_search_petitions_minimal(applicant_name="TechCorp Inc.")

        assert result["petitionDecisionDataBag"][0]["cite_as"] == _PATENT_CENTER_COMPACT

    async def test_balanced_row(self, mock_runtime):
        mock_runtime.api_client.search_petitions.return_value = _bag(_PENDING_ROW)

        result = await fpd_search_petitions_balanced(applicant_name="TechCorp Inc.")

        assert result["petitionDecisionDataBag"][0]["cite_as"] == _PATENT_CENTER_CITE
        assert result["citation_note"] == _NOTE

    async def test_by_art_unit_row(self, mock_runtime):
        mock_runtime.api_client.search_by_art_unit.return_value = _bag(_PENDING_ROW)

        result = await fpd_search_petitions_by_art_unit(art_unit="3643")

        assert result["petitionDecisionDataBag"][0]["cite_as"] == _PATENT_CENTER_CITE
        assert result["citation_note"] == _NOTE

    async def test_by_application_row(self, mock_runtime):
        mock_runtime.api_client.search_by_application.return_value = _bag(_PENDING_ROW)

        result = await fpd_search_petitions_by_application(application_number="12950321")

        assert result["petitionDecisionDataBag"][0]["cite_as"] == _PATENT_CENTER_CITE
        assert result["citation_note"] == _NOTE

    async def test_details_row(self, mock_runtime):
        mock_runtime.api_client.get_petition_by_id.return_value = _bag(
            {**_GRANTED_ROW, "documentBag": []}
        )

        result = await fpd_get_petition_details(petition_id=_PETITION_ID)

        assert result["petitionDecisionDataBag"][0]["cite_as"] == _GOOGLE_PATENTS_CITE
        assert result["citation_note"] == _NOTE

    async def test_a_row_with_no_numbers_gets_no_cite_as(self, mock_runtime):
        """An absent citation is honest; an invented link is not."""
        mock_runtime.api_client.search_petitions.return_value = _bag(
            {"petitionDecisionRecordIdentifier": _PETITION_ID,
             "decisionDate": "2019-06-11"}
        )

        result = await fpd_search_petitions_minimal(applicant_name="TechCorp Inc.")

        assert "cite_as" not in result["petitionDecisionDataBag"][0]

    async def test_empty_result_still_carries_the_note(self, mock_runtime):
        mock_runtime.api_client.search_petitions.return_value = {
            "petitionDecisionDataBag": [], "count": 0,
        }

        result = await fpd_search_petitions_minimal(applicant_name="Nobody")

        assert result["petitionDecisionDataBag"] == []
        assert result["citation_note"] == _NOTE

    async def test_no_cite_as_carries_a_document_delivery_link(self, mock_runtime):
        """A documentBag entry's downloadOptionBag is delivery, not citation.
        Nothing that looks like one may appear inside a cite_as."""
        mock_runtime.api_client.get_petition_by_id.return_value = _bag({
            **_GRANTED_ROW,
            "documentBag": [{
                "documentIdentifier": "ABC123",
                "downloadOptionBag": [{
                    "downloadUrl": "http://localhost:8081/download/persistent/deadbeef",
                }],
            }],
        })

        result = await fpd_get_petition_details(petition_id=_PETITION_ID)

        cite = result["petitionDecisionDataBag"][0]["cite_as"]
        assert "/persistent/" not in cite
        assert "localhost" not in cite


# ---------------------------------------------------------------------------
# Static guarantee
# ---------------------------------------------------------------------------

#: Every source file that can build a citation target.
_CITATION_SOURCES = (
    "src/fpd_mcp/shared/citations.py",
    "src/fpd_mcp/util/citations.py",
)

#: The only two URL forms this server may ever emit as a citation target,
#: both probed live on 2026-09-05 (see shared/citations.py). A third form
#: needs its own probe before it is added here.
_ALLOWED_TARGET_PREFIXES = (
    "https://patents.google.com/patent/",
    "https://patentcenter.uspto.gov/applications/",
)

_URL_LITERAL_RE = re.compile(r"https?://[^\s\"'`)]+")


def test_no_citation_target_is_a_proxy_delivery_link():
    """A static scan, not only a behavioural one: no URL written into the
    citation modules may be a download-proxy path. The hash in those URLs is
    the credential (Lesson 43), so a citation built on one publishes it."""
    root = pathlib.Path(__file__).resolve().parents[1]
    for relative in _CITATION_SOURCES:
        text = (root / relative).read_text(encoding="utf-8")
        for url in _URL_LITERAL_RE.findall(text):
            assert "/document/persistent/" not in url, f"{relative}: {url}"
            assert "/download/persistent/" not in url, f"{relative}: {url}"


def test_only_the_two_verified_url_forms_are_ever_emitted():
    """No third URL form. Anything else needs a live probe first (see the
    shared module's docstring)."""
    assert shared_citations.GOOGLE_PATENTS_BASE == "https://patents.google.com/patent/US"
    assert shared_citations.PATENT_CENTER_BASE == "https://patentcenter.uspto.gov/applications/"

    root = pathlib.Path(__file__).resolve().parents[1]
    for relative in _CITATION_SOURCES:
        text = (root / relative).read_text(encoding="utf-8")
        # Docstrings quote the two forms as examples; both are allowed
        # prefixes, so one rule covers code and prose alike.
        for url in _URL_LITERAL_RE.findall(text):
            assert url.startswith(_ALLOWED_TARGET_PREFIXES), f"{relative}: {url}"


def test_the_shared_module_is_byte_identical_to_ptabs():
    """`shared/citations.py` is a VENDORED module. It carries no fpd_mcp
    import and no repo-specific constant, so it can stay byte-identical with
    the sibling copy; this pins the property that makes that possible."""
    root = pathlib.Path(__file__).resolve().parents[1]
    text = (root / "src/fpd_mcp/shared/citations.py").read_text(encoding="utf-8")
    assert "from .." not in text and "from ." not in text
    assert "import fpd_mcp" not in text and "from fpd_mcp" not in text
    # The only repo names it may mention are the two it is vendored into,
    # named in the docstring so the copy rule cannot be lost.
    assert "FPDFields" not in text


# ---------------------------------------------------------------------------
# The budget the compact form exists for
# ---------------------------------------------------------------------------

_FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


async def test_a_full_minimal_page_fits_the_response_budget(mock_runtime):
    """100 minimal rows, recorded live 2026-09-11 from
    FPD_Search_petitions_minimal(decision_type="DENIED", limit=100) at the
    commit before cite_as (32,023 characters). With the labelled link that
    page measured 44,823 and the guard cut it to 50 rows. It has to fit
    whole again, through the real registrar guard."""
    import json

    from fpd_mcp.shared.response_bounds import BOUNDS_KEY, measure_chars, response_char_budget
    from fpd_mcp.tools import _bound_result

    recorded = json.loads((_FIXTURES / "minimal_denied_limit100.json").read_text())
    mock_runtime.api_client.search_petitions.return_value = recorded

    result = _bound_result(
        await fpd_search_petitions_minimal(decision_type="DENIED", limit=100),
        "FPD_Search_petitions_minimal",
    )

    assert BOUNDS_KEY not in result
    assert result["paging"]["returned"] == 100
    assert result["paging"]["next_offset"] == 100
    assert all(
        row["cite_as"].startswith("<https://") for row in result["petitionDecisionDataBag"]
    )
    assert measure_chars(result) <= response_char_budget()
