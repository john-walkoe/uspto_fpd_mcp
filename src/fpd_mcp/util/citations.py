"""FPD petition row -> `cite_as` markdown links.

The mechanism (number normalization, the two verified URL forms, the
delivery-link refusal, `CITATION_NOTE`) lives in `shared/citations.py`, which
is vendored byte-identical into the sibling USPTO MCPs. THIS module holds the
FPD-specific half: which field on a petition decision record carries the
decision date, the application serial and the patent number, and how a
decision is labelled.

WHAT THE TARGET IS
------------------
A petition decision is a paper in an application's file wrapper. There is no
public per-decision URL: the decision PDF is only reachable through this
server's own download proxy, whose persistent link is a credential and
therefore never a citation. The record a reader can actually open is:

- the patent on Google Patents when the record carries a patent number
  (the application issued, so the patent page is the durable public record);
- otherwise the application on Patent Center.

The LABEL always names the decision and the application, so the reader knows
what the citation is for before clicking: "Petition decision 2019-06-11,
application 12/950,321". A record carrying neither a usable serial nor a
usable patent number gets NO `cite_as` key: an absent citation is honest, a
fabricated link is not.

THE COMPACT FORM (FPD_Search_petitions_minimal only)
----------------------------------------------------
The minimal tier is the 100-row discovery tier, and a labelled link costs
about 115 characters a row. On 2026-09-11 that pushed
FPD_Search_petitions_minimal(decision_type="DENIED", limit=100) from 32,023
characters to 44,823, past the 40,000 response budget, so the guard cut the
page to 50 rows. The label repeats the decision date and application number
the row already carries, so the minimal tier drops it: `cite_as` there is the
same verified URL as a markdown autolink (the URL between angle brackets),
which is still a clickable link and whose visible text names the record.
The same 100 rows then measure 38,712 characters (recorded page in
tests/fixtures/minimal_denied_limit100.json). Every other tier keeps the
labelled form.

THE ENVELOPE NOTE
-----------------
`ENVELOPE_CITATION_NOTE` is a few sentences (335 characters) on every
petition envelope. The full rules (`shared/citations.CITATION_NOTE`, 1,061
characters) live in FPD_get_guidance(section='overview') instead of being
repeated on every response.
"""

from typing import Any, Dict, Optional

from ..api.field_constants import FPDFields
from ..shared.citations import (
    CITATION_NOTE,
    cite_as_link,
    format_application_display,
    google_patents_url,
    is_delivery_link,
    patent_center_url,
)

__all__ = [
    "CITATION_NOTE",
    "CITE_AS_KEY",
    "ENVELOPE_CITATION_NOTE",
    "attach_petition_cite_as",
    "compact_petition_cite_as",
    "petition_cite_as",
]

#: The per-row key. Named once so the attach points, the response-bounds
#: whitelists and the tests cannot drift apart.
CITE_AS_KEY = "cite_as"

#: What every petition envelope carries as `citation_note`. Short on purpose:
#: it rides on every response, and the long text is one guidance call away.
ENVELOPE_CITATION_NOTE = (
    "CITATIONS ARE LINKS. Paste a row's cite_as after any sentence that relies "
    "on that decision; a bare serial or date is not a citation. A "
    "patentcenter.uspto.gov link opens only for a reader signed in with a "
    "free USPTO.gov account, so say so when you paste one. Never cite a "
    "download link. Full rules: FPD_get_guidance(section='overview')."
)

#: Decision-date fields in the order a label should prefer them. decisionDate
#: is in the minimal tier; decisionMailDate is an opt-in field, and
#: petitionMailDate is the filing date, used only when neither decision date
#: is on the record so the label still says WHEN.
_DATE_FIELDS = (
    FPDFields.DECISION_DATE,
    FPDFields.DECISION_MAIL_DATE,
    FPDFields.PETITION_MAIL_DATE,
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _decision_date(record: Dict[str, Any]) -> str:
    for field in _DATE_FIELDS:
        value = _text(record.get(field))
        if value:
            # The API serves plain ISO dates; a datetime is trimmed to the day
            # so a label never carries a timestamp.
            return value[:10]
    return ""


def _petition_url(application_number: Any, patent_number: Any) -> Optional[str]:
    """The public record a petition decision is cited through, or None."""
    return google_patents_url(patent_number) or patent_center_url(application_number)


def petition_cite_as(
    decision_date: Any,
    application_number: Any,
    patent_number: Any = None,
) -> Optional[str]:
    """The markdown `cite_as` for one petition decision, or None when nothing
    is citable."""
    url = _petition_url(application_number, patent_number)
    if not url:
        return None

    date = _text(decision_date)[:10]
    label = f"Petition decision {date}" if date else "Petition decision"
    serial = format_application_display(application_number) or _text(application_number)
    if serial:
        label = f"{label}, application {serial}"
    return cite_as_link(label, url)


def compact_petition_cite_as(
    application_number: Any, patent_number: Any = None
) -> Optional[str]:
    """The minimal tier's `cite_as`: the same verified URL as a markdown
    autolink (the URL between angle brackets), or None when nothing is
    citable. The same delivery-link refusal as `cite_as_link` applies."""
    url = _petition_url(application_number, patent_number)
    if not url or is_delivery_link(url):
        return None
    return f"<{url}>"


def attach_petition_cite_as(result: Any, *, compact: bool = False) -> Any:
    """Stamp `cite_as` on every petition row of a response, in place.

    `compact=True` is the minimal tier's autolink form (module docstring).
    Safe on an error envelope, on an empty result set and on a response whose
    bag key is absent: all three are no-ops. An existing `cite_as` is never
    overwritten.
    """
    if not isinstance(result, dict):
        return result
    records = result.get(FPDFields.PETITION_DECISION_DATA_BAG)
    if not isinstance(records, list):
        return result
    for record in records:
        if not isinstance(record, dict) or record.get(CITE_AS_KEY) is not None:
            continue
        application = record.get(FPDFields.APPLICATION_NUMBER_TEXT)
        patent = record.get(FPDFields.PATENT_NUMBER)
        link = (
            compact_petition_cite_as(application, patent)
            if compact
            else petition_cite_as(_decision_date(record), application, patent)
        )
        if link:
            record[CITE_AS_KEY] = link
    return result


def attach_citation_note(result: Any) -> Any:
    """Put `citation_note` on a petition envelope.

    On the envelope rather than only in the tool docstring: a client that
    never read the description still relays a clickable source. No-op on an
    error envelope.
    """
    if isinstance(result, dict) and "error" not in result:
        result["citation_note"] = ENVELOPE_CITATION_NOTE
    return result


def attach_citations(result: Any, *, compact: bool = False) -> Any:
    """`attach_petition_cite_as` + `attach_citation_note`, the one call every
    petition tool makes on its way out."""
    return attach_citation_note(attach_petition_cite_as(result, compact=compact))
