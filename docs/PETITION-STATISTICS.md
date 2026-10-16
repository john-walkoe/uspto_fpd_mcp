# Petition statistics: API facts and the three tools

Since USPTO's 2026-10 change (docs/UPSTREAM-FPD-API-CHANGE-2026-10.md) the
petition decisions API holds every petition disposition since 2001. Its search
endpoint also counts values per field (`facets`). Three tools, added 2026-10-06,
turn those counts into what a petition practitioner asks for:
`FPD_get_petition_statistics`, `FPD_get_dismissal_grounds` and
`FPD_list_petition_types` (code in `tools/statistics.py`, arithmetic in
`services/petition_statistics.py`, type table in `api/petition_types.py`).

Everything below was probed live on 2026-10-06 (UTC evening, partly
2026-10-07 UTC) through this repo's `FPDClient`, one request per 10 seconds.
Recorded responses: `tests/fixtures/fpd_facets_2026_10_06.json`.

## 1. What the swagger and schema say, and what they do not

- The `reference/FinalPetitionDecisions_swagger.yaml` downloaded on
  2026-10-06 is the combined ODP swagger. It **no longer contains the
  `/api/v1/petition/decisions` paths at all** (the copy it replaced had
  `/search`, `/search/download` and `/{petitionDecisionRecordIdentifier}`).
  Petition material survives only as copy-paste examples under
  `/api/v1/datasets/products/search` (petition field names in the `q`,
  `facets` and `fields` examples) and as schema aliases
  (`PetitionDecisionResponseBag`) pointing at `odp-common-base.yaml`, which is
  not in the download.
- The `facets` parameter is documented only as "List of fields names to be
  faceted upon separated by comma" (GET form). Nothing documents the response
  shape, a value cap, or which fields facet. The facet example list names
  `decisionTypeCode` and `decisionTypeCodeDescriptionText`, both gone since
  2026-10.
- `rangeFilters` is documented as `petitionMailDate 2021-01-01:2025-01-01`
  (GET form); the POST body form `{field, valueFrom, valueTo}` under
  `rangeFilters` is what works (verified 2026-08-30 and again here).
- `reference/petition-decision-schema.json` (2026-10-06): renames
  `lastIngestionDateTime` to `lastModifiedDateTime` and drops
  `applicationNumberText`, `documentDirectionCategory` and
  `pageTotalQuantity` from documentBag entries. It still types
  `decisionPetitionTypeCode` as an integer (it is a string), still lists
  `decisionTypeCode*` (gone), and has no `decidedPetitionTypeCode*`,
  `finalPetitionDecisionIndicator`, `technologyCenter`,
  `decisionMailDate`, `applicationStatus*` or the two index fields. It
  enumerates no petition type codes. The live payload remains the only source.

## 2. Facets, as verified

| fact | evidence |
|---|---|
| POST body key `facets`, a JSON list of field names | `{"facets": ["decidedPetitionTypeCode"], "pagination": {...}}` answered 200 |
| response: `facets: {field: [{value, count}, ...]}`, sorted by count descending | every probe |
| **cap: 1,000 values per field.** A list shorter than 1,000 is complete | `decisionDate`, `petitionMailDate`, `firstApplicantName` came back with exactly 1,000 values; `groupArtUnitNumber` 809, `ruleBag` 348, `decisionPetitionTypeCode` 191 |
| several facets in one call | 8 fields in one call answered 200 |
| facets combine with `q` | `q=finalPetitionDecisionIndicator:true` + facets: counts are for the 7,497 matching records |
| facets combine with `rangeFilters` | decisionDate 2024: 64,889 records, outcome facet sums to it |
| **an unknown field is silently empty**, not an error | `facets: ["noSuchField", ...]` -> `"noSuchField": []`. The tools therefore take dimensions from an allowlist |
| **a nested field is a 500** | `facets: ["documentBag.documentCode"]` -> HTTP 500 "Internal server error occurred" (the client retried it 3 times) |
| `pagination.limit` must be >= 1 | `limit: 0` -> 400 "pagination limit field must be 1 or greater". A counting call asks for one record projected to its identifier |
| dates facet as epoch milliseconds, one value per day | `decisionDate` value `"1271808000000"`; useless for years beyond a few years, hence one query per year |
| deep offsets work | `offset: 50000` and `offset: 556773` answered 200 (no 10,000 window). The search tools keep their own 10,000 cap; the turnaround sample does not need it |
| a nested field works in `q` | `documentBag.documentCode:"PET.DEC.AUTO"` -> 167,405 records |
| free text in `q` reaches the decision text | `decidedPetitionTypeCode:D AND "terminal disclaimer"` -> 23,357 (the records carry the OCR text in `allSearchableFields`) |

Facet value counts on the whole corpus (2026-10-06, 1,113,547 records):
`decidedPetitionTypeCode` 4, `decisionPetitionTypeCode` 191,
`decisionPetitionTypeCodeDescriptionText` 184, `technologyCenter` 56,
`groupArtUnitNumber` 809, `finalDecidingOfficeName` 4, `ruleBag` 348,
`statuteBag` 142, `businessEntityStatusCategory` 3,
`applicationStatusDescriptionText` 60, `firstApplicantName` >= 1,000 (capped),
`petitionIssueConsideredTextBag` 0 on DISMISSED records.

Field coverage that shapes what the tools can say:

- `groupArtUnitNumber` / `technologyCenter`: 1,099,490 of 1,113,547 records
  (14,057 without). Values include letter codes (`OPAP`, `PCTL`, `TTAB`).
  Prefix queries work: `groupArtUnitNumber:371*` (17,518 records),
  `technologyCenter:37*` (187,537 = all of `3700`).
- `ruleBag` / `statuteBag`: 10,137 and 8,978 values in the whole corpus,
  i.e. populated mainly on the final decisions (7,497). **No DISMISSED record
  carries either** (facet on `decidedPetitionTypeCode:D`: both empty), and
  `petitionIssueConsideredTextBag` is empty there too. A dismissal's ground is
  only in its decision document.
- `firstApplicantName` is stored as written: `Samsung Electronics Co., Ltd.`
  (3,088) and `SAMSUNG ELECTRONICS CO., LTD.` (2,233) are separate values.
- ePetition grant letters (`PET.DEC.AUTO`) are on 167,405 records, 167,371 of
  them GRANTED: about 19% of the 880,428 GRANTED. The earlier served
  description "most of them ePetition auto-grants" was not supported by this
  and was replaced with "ePetition auto-grants included". Same-day decisions
  are commoner (104 of a 200-record corpus sample), so automatic processing
  likely reaches beyond the PET.DEC.AUTO letters, but the data does not label it.

The corpus moved between probes: 1,113,650 records on 2026-10-05, 1,113,547
on 2026-10-06 (GRANTED 880,459 -> 880,428, DISMISSED 223,828 -> 223,759,
DENIED 7,499 -> 7,497, GRANTED-IN-PART 1,864 -> 1,863). Every response
carries `as_of`.

## 3. Date filters

Two forms work and the tools use the first:

- In `q`: `decisionDate:[2023-01-01 TO 2023-12-31]`, `petitionMailDate:[2020-01-01 TO *]`.
- In the body: `rangeFilters: [{"field": "decisionDate", "valueFrom": "2024-01-01", "valueTo": "2024-12-31"}]`.

`date_field` is `decisionDate` (default) or `petitionMailDate`. The year
dimension issues one count query per calendar year (at most 12, the 12 most
recent unless `date_start` is given), each with the outcome facet, so every
year carries its own outcome split.

## 4. Petition type table

USPTO publishes no enumeration of `decisionPetitionTypeCode`. The table in
`api/petition_types.py` (191 codes, 184 distinct names) was built on
2026-10-06:

1. Facet both `decisionPetitionTypeCode` and
   `decisionPetitionTypeCodeDescriptionText` over the corpus (1 request).
   133 codes paired where a count was unique on both sides.
2. 10 codes whose count matched no single name (several codes share a name:
   547 and 549 are both "PTA Recalculation"; 273 and 653 share "TO WITHDRAWAL
   A HOLDING OF ABANDONMENT - 37 CFR 1.181"): one facet call each,
   `q=decisionPetitionTypeCode:<code>`, one name each (10 requests).
3. The remaining 48 low-count codes (274 records): every record fetched, each
   code carrying exactly one name (3 requests).

Cross-check (a unit test): for every name, the sum of its codes' counts equals
the name facet's count, over all 191 codes. Names are verbatim, typos and all
("ISUE", "ADDIITONAL"). The table holds no counts; `FPD_list_petition_types`
fetches them live (one facet call, cached in-process for an hour). A live code
not in the table is listed with `name: null`.

The largest classes on 2026-10-06: 643 Track One Request (159,515), 652
Petition to make special-PPH (130,130), 502 revival OPAP/TC unintentional
(104,273), 601 make special on age (59,387). Revival spans 12 codes (271, 272,
292, 501, 502, 510, 536, 560, 561, 562, 566, 571).

## 5. The tools

### FPD_get_petition_statistics

Scope (ANDed, all optional): `petition_type_code` (one or several),
`art_unit` (4 digits or a prefix), `technology_center` (4 digits or a 2-digit
prefix), `rule`, `statute`, `applicant_name`, `deciding_office`,
`decision_type`, `date_field` + `date_start` / `date_end`, `query`,
`final_only`. Breakdowns: `dimensions` (up to 4 of petition_type, art_unit,
technology_center, year, deciding_office, entity_status, applicant, rule,
statute), `top_n` (1-50). `turnaround_sample` (0-500).

Requests: 1 without dimensions; 4 with them (one per outcome: each outcome's
facet lists are one column of the outcome-by-value cross-tab); +1 per year;
+1 per 100 turnaround rows. Reported as `upstream_requests`.

Limits (2026-10-12 audit): at most 16 USPTO requests per call
(`MAX_UPSTREAM_REQUESTS`) and one time budget for the whole call
(`FPD_STATISTICS_DEADLINE_SECONDS`, default 60 s, under claude.ai's ~100 s
cut). The outcome counts always fit the cap; past it the year breakdown keeps
its newest years and the turnaround sample keeps even spacing over fewer
blocks. Whatever is cut (by the cap or the clock) is flagged: `partial`,
`partial_reason` (`request_cap` or `time_budget`), `incomplete_sections`,
`by_year.years_not_counted`, `turnaround.sample_complete: false`. A budget
spent before the outcome counts return answers an authored 408.

Turnaround is the one sampled figure: `ceil(n/100)` blocks of up to 100
consecutive records at evenly spaced offsets of USPTO's order (newest decision
first), days from `petitionMailDate` to `decisionDate`, percentiles p10..p90,
mean, `same_day`, per outcome. The response states the method.

```python
FPD_get_petition_statistics(petition_type_code="502",
                            dimensions=["technology_center", "year"],
                            date_start="2023-01-01", top_n=5,
                            turnaround_sample=200)
```

Live result, 2026-10-07 (UTC), abridged:

```json
{
  "success": true,
  "scope": {"population": "all petition decisions since 2001 (ePetition auto-grants included); final_only=False",
            "filters": {"petition_type_code": [502], "date_range": {"field": "decisionDate", "start": "2023-01-01", "end": null}, "final_only": false},
            "final_query": "decisionPetitionTypeCode:502 AND decisionDate:[2023-01-01 TO *]"},
  "as_of": "2026-10-07",
  "total": 13600,
  "outcomes": {"GRANTED": {"count": 10913, "share": 0.8024}, "GRANTED-IN-PART": {"count": 0, "share": 0.0},
               "DENIED": {"count": 3, "share": 0.0002}, "DISMISSED": {"count": 2684, "share": 0.1974}},
  "rates": {"grant_rate": 0.8024, "grant_rate_incl_partial": 0.8024, "grant_rate_excl_dismissed": 0.9997,
            "denial_rate": 0.0002, "dismissal_rate": 0.1974},
  "dimensions": [{"dimension": "technology_center", "complete": true, "records_without_value": 434,
                  "buckets": [{"value": "3700", "total": 2903, "share_of_scope": 0.2135,
                               "outcomes": {"GRANTED": 2364, "...": "..."}, "rates": {"grant_rate": 0.8143, "...": "..."}}]}],
  "by_year": {"date_field": "decisionDate", "buckets": [{"year": 2026, "total": 2158, "rates": {"grant_rate": 0.8675}},
                                                         {"year": 2023, "total": 4138, "rates": {"grant_rate": 0.7605}}]},
  "turnaround": {"records_sampled": 200, "days": {"p10": 0.0, "p25": 37.0, "median": 47.0, "p75": 57.0, "p90": 67.0, "same_day": 25},
                 "method": "2 block(s) of up to 100 consecutive records at evenly spaced offsets ..."},
  "provenance": "Counts and outcomes are USPTO's own data, quoted: ...",
  "caveats": ["A disposition is not a merits finding. ..."],
  "upstream_requests": 10
}
```

### FPD_get_dismissal_grounds

Same scope minus `decision_type`, `rule`, `statute` and `final_only` (the
final decisions hold no dismissals). Returns dismissal counts by petition type
(with each type's dismissal rate in scope), deciding office, technology
center, rule and statute (the last two say when empty), the `sample_size`
most recent dismissals (max 25) with documentIdentifier, `read_with` and
`cite_as`, and optional `mention_phrases` (max 5) counts of dismissed
decisions whose text contains a phrase, labelled as mentions, not grounds.
Requests: 2 + 1 per phrase. Nothing is downloaded or OCR'd. Same 60 s time
budget; a phrase not counted in time is listed in `mentions_not_counted`.

```python
FPD_get_dismissal_grounds(petition_type_code="502", sample_size=3,
                          mention_phrases=["terminal disclaimer"])
# 2026-10-07: 104,273 type-502 decisions, 17,572 dismissed (16.85%);
# 9,452 of the dismissals mention "terminal disclaimer"; by_rule/by_statute empty.
```

### FPD_list_petition_types

```python
FPD_list_petition_types(search="revival")   # 12 codes, by live count
FPD_list_petition_types(final_only=True)    # what the final decisions are
```

`search` matches every word against USPTO's name (case-insensitive), after
mapping `revival`/`revive` -> `reviv`, `pta` -> "term adjustment" or the word
PTA, `prioritized` -> "track one", `accelerated` -> "special".

## 6. Bounds

Each tool has a `_TOOL_BOUNDS` entry in `tools/__init__.py`: over the 40,000
character budget the bucket lists (and the dismissal sample, the type list)
are halved toward a floor, largest values kept, and `_bounds` says so with a
re-call note. The defaults fit comfortably (the 502 example is 6,289
characters).

## 7. Budget spent building this

51 upstream requests (49 through the probe harness and the smoke wrapper, plus
2 automatic retries of the one 500): 9 facet-shape probes, 7 dismissal and
sampling probes, 13 type-table probes, 3 verification probes, 17 tool calls in
the live smoke (list 1, dismissal 3, statistics 10 + 3).
