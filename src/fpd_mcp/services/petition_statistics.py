"""Aggregation math for the petition statistics tools (pure, no I/O).

Everything countable comes from USPTO's own facet counts on the petition
decisions search endpoint; this module only composes the scope query, merges
facet lists, and does arithmetic on the numbers USPTO returned. The API
facts it relies on were probed live on 2026-10-06 and are written up in
docs/PETITION-STATISTICS.md:

- `facets` is a list of field names in the POST body; the response carries
  `facets: {field: [{value, count}, ...]}`, sorted by count descending and
  capped at 1,000 values per field. A list shorter than the cap is complete.
- Facets combine with `q` (and with `rangeFilters`): the counts are for the
  records the query matched.
- An unknown facet field comes back as an empty list, not an error, so the
  dimensions are an allowlist here.
- Date fields facet as epoch milliseconds, one value per day, and hit the
  1,000-value cap even on a single art unit, so years are counted with one
  date-bounded query per year instead.
- `pagination.limit` must be at least 1, so a counting call still asks for
  one record (projected to its identifier).
"""

import json
import math
import re
from datetime import date
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from ..api.field_constants import FPDFields, QueryFieldNames
from ..api.payload_compat import (
    DECISION_TYPE_CODES,
    FINAL_ONLY_CLAUSE,
    decision_type_clause,
    rewrite_legacy_query_fields,
)
from ..api.petition_types import petition_type_name
from ..shared.error_utils import ValidationError, generate_request_id
from ..validators import validate_date_range, validate_string_param

#: Values per facet field above which USPTO truncates the list (2026-10-06).
FACET_VALUE_CAP = 1000

#: Letter code -> outcome label, in the order the response lists them.
OUTCOME_LABELS: Dict[str, str] = {code: label for label, code in DECISION_TYPE_CODES.items()}
OUTCOME_ORDER: Tuple[str, ...] = ("GRANTED", "GRANTED-IN-PART", "DENIED", "DISMISSED")

#: Dimension name -> the record field USPTO facets it on.
DIMENSION_FIELDS: Dict[str, str] = {
    "petition_type": FPDFields.DECISION_PETITION_TYPE_CODE,
    "art_unit": QueryFieldNames.ART_UNIT,
    "technology_center": QueryFieldNames.TECHNOLOGY_CENTER,
    "deciding_office": FPDFields.FINAL_DECIDING_OFFICE_NAME,
    "entity_status": QueryFieldNames.BUSINESS_ENTITY,
    "applicant": QueryFieldNames.APPLICANT_NAME,
    "rule": QueryFieldNames.RULE,
    "statute": QueryFieldNames.STATUTE,
}

#: The year dimension is not a facet (see the module docstring).
YEAR_DIMENSION = "year"

#: Date fields a scope can be bounded on, and the year dimension counted by.
DATE_FIELDS: Tuple[str, ...] = (
    QueryFieldNames.DECISION_DATE,
    QueryFieldNames.PETITION_MAIL_DATE,
)

MAX_DIMENSIONS = 4
DEFAULT_TOP_N = 15
MAX_TOP_N = 50
MAX_YEARS = 12
MAX_TYPE_CODES = 20
MAX_QUERY_CHARS = 1000

_TYPE_CODE_RE = re.compile(r"^\d{1,4}$")
_ART_UNIT_RE = re.compile(r"^(?:\d{1,4}|[A-Za-z]{2,6})$")
_TC_RE = re.compile(r"^(?:\d{2}|\d{4}|[A-Za-z]{2,6})$")
#: CFR / USC citations carry parentheses and section signs that the generic
#: string allowlist refuses; this one admits them and nothing Lucene-active
#: beyond the parentheses, which travel inside a quoted phrase.
_CITATION_RE = re.compile(r"^[\w\s.,()§/-]+$")
_PHRASE_RE = re.compile(r"^[\w\s.,()§/'&-]+$")


def _fail(message: str) -> None:
    raise ValidationError(message, generate_request_id())


def list_from_text(value: Any) -> Any:
    """A JSON-encoded list sent as a string ('["petition_type", "year"]', '[501, 502]')
    as the list it encodes; anything else unchanged. claude.ai sent the documented
    list form this way and the comma split read it as one bad name (2026-10-07)."""
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = json.loads(value)
        except ValueError:
            return value
        if isinstance(parsed, list):
            return parsed
    return value


def _type_codes(value: Union[None, str, int, Sequence[Union[str, int]]]) -> List[str]:
    """Petition type codes from 502, '502', '501,502', ['501', 502] or '[501, 502]'."""
    value = list_from_text(value)
    if value is None or value == "":
        return []
    if isinstance(value, (str, int)):
        items: Iterable[Any] = str(value).split(",")
    else:
        items = value
    codes: List[str] = []
    for item in items:
        code = str(item).strip()
        if not code:
            continue
        if not _TYPE_CODE_RE.match(code):
            _fail(f"petition_type_code '{code}' is not a type code (digits, e.g. 502). "
                  "Use FPD_list_petition_types to look one up.")
        if code not in codes:
            codes.append(code)
    if len(codes) > MAX_TYPE_CODES:
        _fail(f"At most {MAX_TYPE_CODES} petition type codes per call.")
    return codes


def type_code_clause(value: Union[None, str, int, Sequence[Union[str, int]]]) -> Optional[Tuple[List[str], str]]:
    """(codes, query clause) for one or several petition type codes, or None.

    Shared with the search tools' `petition_type_code` so `'501,502,562'` and
    `[501, 502]` mean the same thing on every tool (the balanced tier used to
    send the comma string verbatim and match nothing).
    """
    codes = _type_codes(value)
    if not codes:
        return None
    field = FPDFields.DECISION_PETITION_TYPE_CODE
    clause = f"{field}:{codes[0]}" if len(codes) == 1 else f"{field}:({' OR '.join(codes)})"
    return codes, clause


def _prefix_or_exact(field: str, value: str, full_length: int) -> str:
    """`field:3711` for a full value, `field:37*` for a shorter digit prefix."""
    if value.isdigit() and len(value) < full_length:
        return f"{field}:{value}*"
    return f"{field}:{value}"


def validate_phrase(value: str, name: str = "phrase", max_length: int = 80) -> str:
    """A phrase that goes out quoted: the CFR-friendly allowlist, no quotes."""
    clean = (value or "").strip()
    if not clean:
        _fail(f"{name} is empty.")
    if len(clean) > max_length:
        _fail(f"{name} too long. Maximum {max_length} characters.")
    if not _PHRASE_RE.match(clean):
        _fail(f"{name} contains invalid characters.")
    return clean


#: One applied filter: (name in `used`, value reported back, query clause).
_Filter = Optional[Tuple[str, Any, str]]


def _query_filter(query: str) -> _Filter:
    q = (query or "").strip()
    if not q:
        return None
    if len(q) > MAX_QUERY_CHARS:
        _fail(f"query too long. Maximum {MAX_QUERY_CHARS} characters.")
    return "query", q, f"({rewrite_legacy_query_fields(q)})"


def _type_code_filter(value: Union[None, str, int, Sequence[Union[str, int]]]) -> _Filter:
    parsed = type_code_clause(value)
    if parsed is None:
        return None
    codes, clause = parsed
    return "petition_type_code", [int(c) for c in codes], clause


def _art_unit_filter(art_unit: Optional[str]) -> _Filter:
    au = (art_unit or "").strip()
    if not au:
        return None
    if not _ART_UNIT_RE.match(au):
        _fail("art_unit must be 1 to 4 digits (fewer than 4 = prefix, e.g. '371') "
              "or a letter code such as 'OPAP'.")
    return "art_unit", au, _prefix_or_exact(QueryFieldNames.ART_UNIT, au.upper(), 4)


def _tc_filter(technology_center: Optional[str]) -> _Filter:
    tc = (technology_center or "").strip()
    if not tc:
        return None
    if not _TC_RE.match(tc):
        _fail("technology_center must be 4 digits ('3700'), a 2-digit prefix ('37') "
              "or a letter code such as 'OPAP'.")
    return "technology_center", tc, _prefix_or_exact(QueryFieldNames.TECHNOLOGY_CENTER, tc.upper(), 4)


def _citation_filter(name: str, value: Optional[str], field: str) -> _Filter:
    clean = (value or "").strip()
    if not clean:
        return None
    if len(clean) > 60 or not _CITATION_RE.match(clean):
        _fail(f"{name} must be a citation such as '37 CFR 1.137' (60 characters at most, "
              "letters, digits, spaces and . , ( ) § / - only).")
    return name, clean, f'{field}:"{clean}"'


def _phrase_field_filter(name: str, value: Optional[str], field: str) -> _Filter:
    clean = validate_string_param(name, value)
    if not clean:
        return None
    return name, clean, f'{field}:"{clean}"'


def _decision_filter(decision_type: Optional[str]) -> _Filter:
    clean = validate_string_param("decision_type", decision_type, 50)
    if not clean:
        return None
    return "decision_type", clean.upper(), decision_type_clause(clean)


def _date_filter(date_field: str, date_start: Optional[str], date_end: Optional[str]) -> _Filter:
    if date_field not in DATE_FIELDS:
        _fail(f"date_field must be one of {', '.join(DATE_FIELDS)}.")
    start = validate_date_range(date_start) if date_start else None
    end = validate_date_range(date_end) if date_end else None
    if start and end and start > end:
        _fail("date_start is after date_end.")
    if not (start or end):
        return None
    return (
        "date_range",
        {"field": date_field, "start": start, "end": end},
        f"{date_field}:[{start or '*'} TO {end or '*'}]",
    )


def compose_scope(
    *,
    query: str = "",
    petition_type_code: Union[None, str, int, Sequence[Union[str, int]]] = None,
    art_unit: Optional[str] = None,
    technology_center: Optional[str] = None,
    rule: Optional[str] = None,
    statute: Optional[str] = None,
    applicant_name: Optional[str] = None,
    deciding_office: Optional[str] = None,
    decision_type: Optional[str] = None,
    date_field: str = QueryFieldNames.DECISION_DATE,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    final_only: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    """(Lucene query, the filters as applied) for one statistics scope.

    Every filter is ANDed. An empty scope is legal here (the whole corpus),
    unlike the search tools: counting everything is a meaningful question.
    It goes out as no `q` at all, which USPTO answers with the whole corpus.
    """
    filters = (
        _query_filter(query),
        _type_code_filter(petition_type_code),
        _art_unit_filter(art_unit),
        _tc_filter(technology_center),
        _citation_filter("rule", rule, QueryFieldNames.RULE),
        _citation_filter("statute", statute, QueryFieldNames.STATUTE),
        _phrase_field_filter("applicant_name", applicant_name, QueryFieldNames.APPLICANT_NAME),
        _phrase_field_filter("deciding_office", deciding_office, FPDFields.FINAL_DECIDING_OFFICE_NAME),
        _decision_filter(decision_type),
        _date_filter(date_field, date_start, date_end),
    )
    parts: List[str] = []
    used: Dict[str, Any] = {}
    for applied in filters:
        if applied is not None:
            name, value, clause = applied
            parts.append(clause)
            used[name] = value
    if final_only:
        parts.append(FINAL_ONLY_CLAUSE)
    used["final_only"] = bool(final_only)
    return " AND ".join(parts), used


def and_clause(scope_query: str, clause: str) -> str:
    """The scope query narrowed by one more clause."""
    if not scope_query:
        return clause
    return f"{scope_query} AND {clause}"


def outcome_clause(code: str) -> str:
    return f"{FPDFields.DECIDED_PETITION_TYPE_CODE}:{code}"


# ---------------------------------------------------------------------------
# Rates
# ---------------------------------------------------------------------------

def _ratio(numerator: int, denominator: int) -> Optional[float]:
    return round(numerator / denominator, 4) if denominator else None


def outcome_counts(facet: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, int]:
    """A `decidedPetitionTypeCode` facet list as {GRANTED: n, ...}, every
    outcome present (0 when USPTO listed none)."""
    counts = {label: 0 for label in OUTCOME_ORDER}
    for bucket in facet or ():
        label = OUTCOME_LABELS.get(str(bucket.get("value", "")).strip().upper())
        if label:
            counts[label] += int(bucket.get("count") or 0)
    return counts


def rates(counts: Mapping[str, int]) -> Dict[str, Optional[float]]:
    """Shares of the outcome counts. None where the denominator is zero.

    - grant_rate: GRANTED / all
    - grant_rate_incl_partial: (GRANTED + GRANTED-IN-PART) / all
    - grant_rate_excl_dismissed: (GRANTED + GRANTED-IN-PART) / (all - DISMISSED),
      the share granted among petitions decided on the request rather than
      dismissed
    - denial_rate: DENIED / all
    - dismissal_rate: DISMISSED / all
    """
    total = sum(counts.get(label, 0) for label in OUTCOME_ORDER)
    granted = counts.get("GRANTED", 0)
    partial = counts.get("GRANTED-IN-PART", 0)
    dismissed = counts.get("DISMISSED", 0)
    return {
        "grant_rate": _ratio(granted, total),
        "grant_rate_incl_partial": _ratio(granted + partial, total),
        "grant_rate_excl_dismissed": _ratio(granted + partial, total - dismissed),
        "denial_rate": _ratio(counts.get("DENIED", 0), total),
        "dismissal_rate": _ratio(dismissed, total),
    }


def outcome_block(counts: Mapping[str, int]) -> Dict[str, Any]:
    """{total, outcomes: {label: {count, share}}, rates} for one population."""
    total = sum(counts.get(label, 0) for label in OUTCOME_ORDER)
    return {
        "total": total,
        "outcomes": {
            label: {"count": counts.get(label, 0), "share": _ratio(counts.get(label, 0), total)}
            for label in OUTCOME_ORDER
        },
        "rates": rates(counts),
    }


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

def _facet_map(facet: Optional[Sequence[Mapping[str, Any]]]) -> Dict[str, int]:
    return {str(b.get("value")): int(b.get("count") or 0) for b in facet or () if b.get("value") is not None}


def _bucket_label(dimension: str, value: str) -> Dict[str, Any]:
    if dimension == "petition_type":
        try:
            code: Any = int(value)
        except ValueError:
            code = value
        return {"code": code, "name": petition_type_name(value)}
    return {"value": value}


def dimension_table(
    dimension: str,
    per_outcome_facets: Mapping[str, Optional[Sequence[Mapping[str, Any]]]],
    scope_total: int,
    top_n: int,
) -> Dict[str, Any]:
    """One dimension's buckets with their outcome split, from one facet list
    per outcome (each call scoped to that outcome).

    A bucket's total is the sum of its four outcome counts. When an outcome's
    list hit the 1,000-value cap and a bucket is missing from it, that count
    is unknown rather than zero: the bucket is flagged `partial` and its
    rates are computed over what is known.
    """
    maps = {label: _facet_map(per_outcome_facets.get(label)) for label in OUTCOME_ORDER}
    capped = {label: len(per_outcome_facets.get(label) or ()) >= FACET_VALUE_CAP for label in OUTCOME_ORDER}

    totals: Dict[str, int] = {}
    for counts in maps.values():
        for value, count in counts.items():
            totals[value] = totals.get(value, 0) + count
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))

    buckets = []
    for value, total in ranked[:top_n]:
        counts = {label: maps[label].get(value, 0) for label in OUTCOME_ORDER}
        unknown = [label for label in OUTCOME_ORDER if capped[label] and value not in maps[label]]
        bucket = _bucket_label(dimension, value)
        bucket.update({
            "total": total,
            "share_of_scope": _ratio(total, scope_total),
            "outcomes": counts,
            "rates": rates(counts),
        })
        if unknown:
            bucket["partial"] = {
                "outcomes_unknown": unknown,
                "note": "This value fell outside USPTO's 1,000-value facet list for these "
                        "outcomes, so their counts are unknown (not zero).",
            }
        buckets.append(bucket)

    complete = not any(capped.values())
    with_value = sum(totals.values())
    table: Dict[str, Any] = {
        "dimension": dimension,
        "field": DIMENSION_FIELDS[dimension],
        "distinct_values": len(totals) if complete else None,
        "values_shown": len(buckets),
        "complete": complete,
        "buckets": buckets,
    }
    if complete:
        table["records_without_value"] = max(0, scope_total - with_value) if dimension not in ("rule", "statute") else None
        if len(buckets) < len(totals):
            # `complete` is about USPTO's facet list, not this table: a value
            # below the top_n cut is present in the scope, not zero (a reader
            # took 'complete: true' over 30 of 62 types as the whole table,
            # skills re-test 2026-10-07).
            table["truncated_by_top_n"] = {
                "values_shown": len(buckets),
                "distinct_values": len(totals),
                "note": (f"Only the top {len(buckets)} of {len(totals)} values are listed. "
                         "A value missing from this table is below the cut, not zero: raise "
                         "top_n (maximum 50) or pass it as a filter (e.g. petition_type_code) "
                         "to count it."),
            }
    else:
        table["note"] = ("At least one outcome had more than 1,000 distinct values, so USPTO "
                         "returned only its top 1,000 and the distinct count is unknown.")
    if dimension in ("rule", "statute"):
        table["values_are_multi"] = (
            f"{DIMENSION_FIELDS[dimension]} is a list: one petition can carry several values, "
            "so bucket totals can add up to more than the petitions in scope, and most "
            "records carry none (populated mainly on the final decisions)."
        )
    if dimension == "applicant":
        table["values_are_as_written"] = (
            "firstApplicantName is stored as written, so one company can appear under "
            "several spellings ('Samsung Electronics Co., Ltd.' and 'SAMSUNG ELECTRONICS "
            "CO., LTD.' are separate values). Many records carry no applicant name."
        )
    return table


# ---------------------------------------------------------------------------
# Years
# ---------------------------------------------------------------------------

def year_windows(
    date_start: Optional[str], date_end: Optional[str], today: date, max_years: int = MAX_YEARS
) -> Tuple[List[Tuple[int, str, str]], Dict[str, Any]]:
    """[(year, first day, last day)] for the year dimension, newest first,
    clipped to the scope's date range, at most `max_years` of them.

    Without a start date the window is the `max_years` most recent calendar
    years (the corpus reaches back to 2001; a caller who wants older years
    passes date_start). The second value says what was cut, if anything.
    """
    end = date.fromisoformat(date_end) if date_end else today
    first_year = int(date_start[:4]) if date_start else end.year - max_years + 1
    years = list(range(end.year, first_year - 1, -1))
    info: Dict[str, Any] = {"years_in_scope": len(years)}
    if len(years) > max_years:
        info["years_omitted"] = {"from": years[max_years:][-1], "to": years[max_years]}
        years = years[:max_years]
    elif not date_start:
        info["default_window"] = True
    windows = []
    for year in years:
        lo = f"{year}-01-01"
        hi = f"{year}-12-31"
        if date_start and year == int(date_start[:4]):
            lo = date_start
        if year == end.year:
            hi = end.isoformat()
        windows.append((year, lo, hi))
    return windows, info


# ---------------------------------------------------------------------------
# Turnaround sampling
# ---------------------------------------------------------------------------

PAGE_SIZE = 100
MAX_SAMPLE = 500


def sample_pages(total: int, sample_size: int, page_size: int = PAGE_SIZE) -> List[Tuple[int, int]]:
    """(offset, limit) blocks for a systematic sample of `sample_size` rows.

    The whole scope when it fits; otherwise ceil(sample_size / page_size)
    blocks at evenly spaced offsets across the result list (USPTO's order,
    newest decision first). Each block is a run of consecutive records, so
    this is a systematic cluster sample, not a random one.
    """
    if total <= 0 or sample_size <= 0:
        return []
    want = min(sample_size, total)
    pages = math.ceil(want / page_size)
    if total <= pages * page_size:
        return [(offset, min(page_size, total - offset)) for offset in range(0, total, page_size)][:pages]
    last_page = want - (pages - 1) * page_size
    stride = total / pages
    blocks = []
    for i in range(pages):
        limit = page_size if i < pages - 1 else last_page
        offset = min(int(i * stride), total - limit)
        blocks.append((offset, limit))
    return blocks


def _percentile(sorted_values: Sequence[int], pct: float) -> Optional[float]:
    """Linear-interpolated percentile of an already sorted list."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (len(sorted_values) - 1) * pct / 100.0
    lo = math.floor(rank)
    hi = math.ceil(rank)
    value = sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (rank - lo)
    return round(value, 1)


def _days(record: Mapping[str, Any]) -> Optional[int]:
    try:
        mailed = date.fromisoformat(str(record.get(QueryFieldNames.PETITION_MAIL_DATE))[:10])
        decided = date.fromisoformat(str(record.get(QueryFieldNames.DECISION_DATE))[:10])
    except ValueError:
        return None
    return (decided - mailed).days


def _spread(values: List[int]) -> Dict[str, Any]:
    values = sorted(values)
    return {
        "n": len(values),
        "p10": _percentile(values, 10),
        "p25": _percentile(values, 25),
        "median": _percentile(values, 50),
        "p75": _percentile(values, 75),
        "p90": _percentile(values, 90),
        "mean": round(sum(values) / len(values), 1) if values else None,
        "same_day": sum(1 for v in values if v == 0),
    }


def turnaround_stats(records: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Days from petitionMailDate to decisionDate over the sampled records,
    overall and per outcome. Records missing a date, or deciding before the
    mail date, are counted and left out."""
    overall: List[int] = []
    by_outcome: Dict[str, List[int]] = {label: [] for label in OUTCOME_ORDER}
    missing = negative = 0
    for record in records:
        days = _days(record)
        if days is None:
            missing += 1
            continue
        if days < 0:
            negative += 1
            continue
        overall.append(days)
        label = OUTCOME_LABELS.get(str(record.get(FPDFields.DECIDED_PETITION_TYPE_CODE, "")).upper())
        if label:
            by_outcome[label].append(days)
    return {
        "days": _spread(overall),
        "by_outcome": {label: _spread(v) for label, v in by_outcome.items() if v},
        "excluded": {"missing_a_date": missing, "decided_before_mail_date": negative},
    }
