"""The ten prompt templates render, interpolate, and honor their flags.

T-2 (testing-implementation): `test_prompts_gate.py` proves the ten modules
IMPORT (it launches a subprocess with FPD_ENABLE_PROMPTS=true, which imports
them all), so a SyntaxError or a malformed f-string brace is caught. Nothing
called any of them, leaving 3,600-odd lines of template verified only for "it
parses". Two known drift classes hid in that gap and are pinned here:

- R-2: the boolean options are `str` compared exactly against "true", so
  `True`, `"True"`, `"yes"` and `"1"` all silently dropped the optional
  section. `prompts/_flags.py::flag` now normalizes at the entry point.
- R-7: a worked example carried `limit=200` after MAX_SEARCH_LIMIT dropped to
  100, so the template promised "comprehensive" and silently got a page.
"""

import re

import pytest

from fpd_mcp.config import api_constants
from fpd_mcp.prompts import (
    art_unit_quality_assessment,
    company_petition_risk_assessment_pfw,
    complete_portfolio_due_diligence_pfw_ptab,
    examiner_dispute_citation_analysis,
    litigation_research_setup_pfw,
    patent_vulnerability_assessment_ptab,
    petition_document_research_package,
    petition_quality_with_citation_intelligence,
    prosecution_quality_correlation_pfw,
    revival_petition_analysis,
)
from fpd_mcp.prompts._flags import flag

_CASES = [
    (art_unit_quality_assessment.art_unit_quality_assessment_prompt,
     {"art_unit": "2128"}),
    (company_petition_risk_assessment_pfw.company_petition_risk_assessment_prompt,
     {"company_name": "TechCorp Inc"}),
    (complete_portfolio_due_diligence_pfw_ptab.complete_portfolio_due_diligence_prompt,
     {"company_name": "TechCorp Inc"}),
    (examiner_dispute_citation_analysis.examiner_dispute_citation_analysis_prompt,
     {"examiner_name": "Jane Examiner"}),
    (litigation_research_setup_pfw.litigation_research_setup_prompt,
     {"patent_number": "9999999"}),
    (patent_vulnerability_assessment_ptab.patent_vulnerability_assessment_ptab_prompt,
     {"company_name": "TechCorp Inc"}),
    (petition_document_research_package.petition_document_research_package_prompt,
     {"application_number": "13408005"}),
    (petition_quality_with_citation_intelligence.petition_quality_with_citation_intelligence_prompt,
     {"art_unit": "2128"}),
    (prosecution_quality_correlation_pfw.prosecution_quality_correlation_prompt,
     {"art_unit": "2128"}),
    (revival_petition_analysis.revival_petition_analysis_prompt,
     {"company_name": "TechCorp Inc"}),
]

#: The boolean option each prompt exposes, and whether it defaults on.
_FLAG_PARAMS = {
    art_unit_quality_assessment.art_unit_quality_assessment_prompt:
        ("comparison_analysis", {"art_unit": "2128"}),
    company_petition_risk_assessment_pfw.company_petition_risk_assessment_prompt:
        ("include_details", {"company_name": "TechCorp Inc"}),
    complete_portfolio_due_diligence_pfw_ptab.complete_portfolio_due_diligence_prompt:
        ("risk_scoring", {"company_name": "TechCorp Inc"}),
    examiner_dispute_citation_analysis.examiner_dispute_citation_analysis_prompt:
        ("include_comparison", {"examiner_name": "Jane Examiner"}),
    litigation_research_setup_pfw.litigation_research_setup_prompt:
        ("include_prosecution", {"patent_number": "9999999"}),
    patent_vulnerability_assessment_ptab.patent_vulnerability_assessment_ptab_prompt:
        ("predictive_analysis", {"company_name": "TechCorp Inc"}),
    petition_quality_with_citation_intelligence.petition_quality_with_citation_intelligence_prompt:
        ("include_citation_analysis", {"art_unit": "2128"}),
    prosecution_quality_correlation_pfw.prosecution_quality_correlation_prompt:
        ("statistical_analysis", {"art_unit": "2128"}),
    revival_petition_analysis.revival_petition_analysis_prompt:
        ("include_reasoning", {"company_name": "TechCorp Inc"}),
}

_LIMIT_RE = re.compile(r"limit\s*=\s*(\d+)")


def _ids(case):
    return getattr(case[0], "__name__", "")


@pytest.mark.parametrize("fn,kwargs", _CASES, ids=[_ids(c) for c in _CASES])
async def test_prompt_renders_and_interpolates(fn, kwargs):
    out = await fn(**kwargs)

    assert isinstance(out, str)
    assert len(out) > 500
    for value in kwargs.values():
        assert value in out, f"{fn.__name__} dropped {value!r}"


@pytest.mark.parametrize(
    "fn,kwargs", _CASES, ids=[_ids(c) for c in _CASES]
)
async def test_prompt_header_has_no_unfilled_placeholder(fn, kwargs):
    """The prose above the first fenced block is template output, not code:
    a stray `{name}` there is an interpolation the author forgot."""
    header = (await fn(**kwargs)).split("```")[0]

    assert not re.search(r"\{[a-z_]+\}", header), header[-300:]


@pytest.mark.parametrize("truthy", [True, "True", "TRUE", "yes", "1", "on"])
@pytest.mark.parametrize(
    "fn", list(_FLAG_PARAMS), ids=[f.__name__ for f in _FLAG_PARAMS]
)
async def test_default_on_flag_is_honored_for_any_truthy_encoding(fn, truthy):
    """R-2: every one of these used to render `if "True" == "true":`."""
    param, kwargs = _FLAG_PARAMS[fn]

    out = await fn(**kwargs, **{param: truthy})

    assert '"true" == "true"' in out
    assert f'"{truthy}" == "true"' not in out


@pytest.mark.parametrize("falsy", [False, "False", "FALSE", "no", "0", "off"])
@pytest.mark.parametrize(
    "fn", list(_FLAG_PARAMS), ids=[f.__name__ for f in _FLAG_PARAMS]
)
async def test_default_on_flag_can_actually_be_turned_off(fn, falsy):
    param, kwargs = _FLAG_PARAMS[fn]

    out = await fn(**kwargs, **{param: falsy})

    assert '"false" == "true"' in out
    assert f'"{falsy}" == "true"' not in out


async def test_default_off_flag_normalizes_too():
    """petition_document_research_package's extract_text defaults false."""
    on = await petition_document_research_package.petition_document_research_package_prompt(
        application_number="13408005", extract_text=True
    )
    off = await petition_document_research_package.petition_document_research_package_prompt(
        application_number="13408005"
    )

    assert '"true"' in on
    assert '"false"' in off


@pytest.mark.parametrize("fn,kwargs", _CASES, ids=[_ids(c) for c in _CASES])
async def test_fpd_search_examples_respect_the_search_ceiling(fn, kwargs):
    """R-7: a constant change that invalidates a worked example fails here
    instead of shipping. Only FPD_ calls are checked — the PFW/PTAB examples
    target other servers with their own ceilings."""
    out = await fn(**kwargs)

    lines = out.splitlines()
    for index, line in enumerate(lines):
        match = _LIMIT_RE.search(line)
        if not match:
            continue
        window = "\n".join(lines[max(0, index - 12):index + 1])
        if "FPD_Search_petitions" not in window:
            continue
        assert int(match.group(1)) <= api_constants.MAX_SEARCH_LIMIT, line


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, "true"), (False, "false"),
        ("true", "true"), ("True", "true"), ("TRUE", "true"),
        ("yes", "true"), ("y", "true"), ("1", "true"), ("on", "true"),
        ("false", "false"), ("False", "false"), ("no", "false"),
        ("0", "false"), ("off", "false"),
        (None, "true"), ("", "true"),
        ("banana", "true"),  # unrecognized falls back to the default
    ],
)
def test_flag_normalizes_every_encoding_a_caller_sends(value, expected):
    assert flag(value) == expected


@pytest.mark.parametrize("value", [None, "", "banana"])
def test_flag_respects_a_false_default(value):
    assert flag(value, default=False) == "false"
