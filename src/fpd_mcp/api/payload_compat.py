"""Adapter for the October 2026 FPD payload change.

USPTO changed the Final Petition Decisions API payload between 2026-10-03 and
2026-10-05 with no notice and no change on this side. The full field-by-field
record is docs/UPSTREAM-FPD-API-CHANGE-2026-10.md; what this module absorbs,
probed live on 2026-10-05:

- The decision outcome moved from `decisionTypeCodeDescriptionText` /
  `decisionTypeCode` to `decidedPetitionTypeCodeDescriptionText` /
  `decidedPetitionTypeCode`. A query on the old name now answers 404 (empty)
  and a `fields` projection naming it is silently ignored. Every consumer in
  this repo (field sets, the UI, the prompts, the download tool's
  document_context) reads the old name, so records keep it as an alias of the
  new one, and projections ask for both.
- The outcome text field is ANALYZED: `decidedPetitionTypeCodeDescriptionText:
  GRANTED` also matches GRANTED-IN-PART (882,323 vs 880,459). The letter code
  is exact, so a decision filter goes out on `decidedPetitionTypeCode`.
- `decisionPetitionTypeCode` arrives as a string ("551") where it was an
  integer, and USPTO's published schema still says integer. Records are
  normalised back to the integer, which is the representation this server
  has always served.
- Every record now carries two search-index fields: `allSearchableFields`
  (every field concatenated with the decision's full OCR text, ~25,000
  characters on one petition) and `ocrSearchText` (a 500-character OCR
  snippet). Both are dropped: they blow the response budget, duplicate the
  record, and carry document text that must go through the content tool
  (where it is injection-scanned) rather than ride along unscanned.
- documentBag is now native on every record, details and search alike, with
  `pageTotalQuantity` only inside downloadOptionBag; `pageCount` is backfilled
  at the top level as it already was for file-wrapper bags.

Pure functions, no I/O.
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from .field_constants import FPDFields

#: Legacy record key -> the key USPTO serves since 2026-10.
LEGACY_FIELD_ALIASES: Dict[str, str] = {
    FPDFields.DECISION_TYPE_CODE_DESCRIPTION_TEXT: FPDFields.DECIDED_PETITION_TYPE_CODE_DESCRIPTION_TEXT,
    FPDFields.DECISION_TYPE_CODE: FPDFields.DECIDED_PETITION_TYPE_CODE,
}

#: Search-index fields USPTO now returns on every record. Never served.
INDEX_ONLY_FIELDS: Tuple[str, ...] = (
    FPDFields.ALL_SEARCHABLE_FIELDS,
    FPDFields.OCR_SEARCH_TEXT,
)

#: Outcome text -> exact letter code. Each pairing is an exact facet-count
#: match on 2026-10-05 (A 880,459 = GRANTED 880,459; B 1,864 = GRANTED-IN-PART;
#: C 7,499 = DENIED; D 223,828 = DISMISSED).
DECISION_TYPE_CODES: Dict[str, str] = {
    "GRANTED": "A",
    "GRANTED-IN-PART": "B",
    "DENIED": "C",
    "DISMISSED": "D",
}

#: The ODP document-download URL shape served in native downloadOptionBag
#: entries (probed 2026-10-05: 302 to data-documents.uspto.gov, then %PDF).
_DOWNLOAD_URL_TEMPLATE = (
    "https://api.uspto.gov/api/v1/download/applications/{application}/{document}.pdf"
)

_LEGACY_DECISION_FIELD_RE = re.compile(
    r"\b" + re.escape(FPDFields.DECISION_TYPE_CODE_DESCRIPTION_TEXT) + r"(?=\s*:)"
)


def normalize_type_code(value: Any) -> Any:
    """'551' -> 551; an int stays an int; anything non-numeric is untouched."""
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value


def type_code_query_value(value: Union[str, int]) -> str:
    """A petition type code as it goes into a query, from an int or a string."""
    return str(value).strip()


#: The query clause that restricts a search to the final petition decisions
#: (the pre-2026-10 population; every record in it was DENIED on 2026-10-05).
FINAL_ONLY_CLAUSE = f"{FPDFields.FINAL_PETITION_DECISION_INDICATOR}:true"


def decision_type_clause(value: str) -> str:
    """The query clause for a decision_type filter.

    A known outcome goes out on the exact letter code; anything else on the
    description text, quoted, so an unknown value still reaches USPTO and
    comes back as an honest zero rather than being dropped here.
    """
    normalized = value.strip().upper()
    code = DECISION_TYPE_CODES.get(normalized)
    if code is not None:
        return f"{FPDFields.DECIDED_PETITION_TYPE_CODE}:{code}"
    return f'{FPDFields.DECIDED_PETITION_TYPE_CODE_DESCRIPTION_TEXT}:"{value.strip()}"'


def rewrite_legacy_query_fields(query: str) -> str:
    """Point a raw-query clause on the retired outcome field at its new name.

    Records still carry `decisionTypeCodeDescriptionText` (as an alias), so a
    caller who queries on a key it can see would otherwise get a silent zero.
    """
    return _LEGACY_DECISION_FIELD_RE.sub(
        FPDFields.DECIDED_PETITION_TYPE_CODE_DESCRIPTION_TEXT, query
    )


def upstream_fields(fields: Optional[Iterable[str]]) -> Optional[List[str]]:
    """A `fields` projection with the current name added beside each legacy
    one. USPTO ignores a name it does not know, so asking for both is safe in
    either direction."""
    if fields is None:
        return None
    out: List[str] = []
    for field in fields:
        if field not in out:
            out.append(field)
        current = LEGACY_FIELD_ALIASES.get(field)
        if current and current not in out:
            out.append(current)
    return out


def backfill_page_counts(document_bag: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Copy the PDF option's pageTotalQuantity to a top-level pageCount on
    every documentBag entry that lacks one. Both the native FPD bag (since
    2026-10) and the application file-wrapper bag carry the count only inside
    downloadOptionBag, and the extraction resolver and the size guard's slim
    field set read the top-level key."""
    for doc in document_bag:
        if not isinstance(doc, dict) or doc.get(FPDFields.PAGE_COUNT):
            continue
        for option in doc.get(FPDFields.DOWNLOAD_OPTION_BAG) or []:
            if isinstance(option, dict) and option.get(FPDFields.MIME_TYPE_IDENTIFIER) == "PDF":
                page_total = option.get(FPDFields.PAGE_TOTAL_QUANTITY)
                if page_total:
                    doc[FPDFields.PAGE_COUNT] = page_total
                break
    return document_bag


def normalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise one petition record in place (see the module docstring)."""
    if not isinstance(record, dict):
        return record
    for field in INDEX_ONLY_FIELDS:
        record.pop(field, None)
    if FPDFields.DECISION_PETITION_TYPE_CODE in record:
        record[FPDFields.DECISION_PETITION_TYPE_CODE] = normalize_type_code(
            record[FPDFields.DECISION_PETITION_TYPE_CODE]
        )
    for legacy, current in LEGACY_FIELD_ALIASES.items():
        if legacy not in record and current in record:
            record[legacy] = record[current]
    bag = record.get(FPDFields.DOCUMENT_BAG)
    if isinstance(bag, list):
        backfill_page_counts(bag)
    return record


def normalize_response(result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise every record of a search or details response in place."""
    if not isinstance(result, dict):
        return result
    records = result.get(FPDFields.PETITION_DECISION_DATA_BAG)
    if isinstance(records, list):
        for record in records:
            normalize_record(record)
    return result


def select_pdf_download(
    document: Dict[str, Any], application_number: Optional[str]
) -> Tuple[Optional[str], int]:
    """(USPTO PDF download URL, page count) for one documentBag entry.

    Native entries can list more than one PDF option: an ePetition grant
    (PET.DEC.AUTO) carries the document itself at `<id>.pdf` and a second
    `/files/grantLetter.pdf`. The document's own `<id>.pdf` is preferred, then
    the first PDF option. An entry with no PDF option at all gets the URL
    built from the documented pattern when the application number and
    identifier are known; otherwise (None, count).
    """
    document_identifier = document.get(FPDFields.DOCUMENT_IDENTIFIER)
    pdf_options = [
        option
        for option in document.get(FPDFields.DOWNLOAD_OPTION_BAG) or []
        if isinstance(option, dict)
        and option.get(FPDFields.MIME_TYPE_IDENTIFIER) == "PDF"
        and option.get(FPDFields.DOWNLOAD_URL)
    ]
    chosen = None
    if document_identifier:
        suffix = f"/{document_identifier}.pdf"
        chosen = next(
            (o for o in pdf_options if str(o[FPDFields.DOWNLOAD_URL]).endswith(suffix)),
            None,
        )
    if chosen is None and pdf_options:
        chosen = pdf_options[0]
    page_count = document.get(FPDFields.PAGE_COUNT) or 0
    if chosen is not None:
        return chosen[FPDFields.DOWNLOAD_URL], chosen.get(FPDFields.PAGE_TOTAL_QUANTITY) or page_count
    if document_identifier and application_number:
        return (
            _DOWNLOAD_URL_TEMPLATE.format(
                application=application_number, document=document_identifier
            ),
            page_count,
        )
    return None, page_count
