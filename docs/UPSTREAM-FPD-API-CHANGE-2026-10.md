# USPTO FPD API payload change, October 2026

USPTO changed the Final Petition Decisions API
(`https://api.uspto.gov/api/v1/petition/decisions`) between 2026-10-03 and
2026-10-05. Nothing changed on this side; the server's own live checks began
failing on 2026-10-03 and failed more widely on 2026-10-05.

Everything below was probed live on 2026-10-05 with this repo's request headers
(`X-API-KEY`, `Content-Type`/`Accept: application/json`, the default httpx
User-Agent), at most one request every 10 seconds. The recorded samples are in
`tests/fixtures/fpd_payload_2026_10.json`.

USPTO's published schema (`https://data.uspto.gov/documents/documents/petition-decision-schema.json`,
read once on 2026-10-05) has **not** caught up. It still lists
`decisionTypeCodeDescriptionText` and `decisionTypeCode`, types
`decisionPetitionTypeCode` as an integer, and has no
`decidedPetitionTypeCode*`, `finalPetitionDecisionIndicator`, `ocrSearchText`
or `allSearchableFields`. The live payload is the only source for what follows.

## 1. Corpus

| | before (2026-08-30) | after (2026-10-05) |
|---|---|---|
| unfiltered `count` | ~7,500 | 1,113,650 |
| outcome mix | 7,481 DENIED, 6 DISMISSED, 2 GRANTED | 880,459 GRANTED, 223,828 DISMISSED, 7,499 DENIED, 1,864 GRANTED-IN-PART |
| `finalPetitionDecisionIndicator` | (field absent) | true on 7,499 records, false on 1,106,151 |
| distinct `decisionPetitionTypeCode` values (facet) | not enumerated (the observed table in `api/field_constants.py`) | 191 |

The corpus now holds every petition decision from 2001 on, including ePetition
auto-grants (`PET.DEC.AUTO`, "ePetition Grant Letter"), not only final
decisions. The old population matches the records whose
`finalPetitionDecisionIndicator` is true: 7,499 records, and every one is
DENIED (facet on `q=finalPetitionDecisionIndicator:true`). The query syntax
`finalPetitionDecisionIndicator:true` works.

## 2. Field by field

| field | before | after | server handling |
|---|---|---|---|
| `decisionTypeCodeDescriptionText` | GRANTED / DENIED / DISMISSED | **gone**. A query on it answers HTTP 404 ("No matching records found"), and a `fields` projection naming it is silently ignored | records keep it as an alias of the new field; projections ask for both names; a raw query clause on it is rewritten to the new name |
| `decisionTypeCode` | letter code | **gone** | alias of `decidedPetitionTypeCode` |
| `decidedPetitionTypeCodeDescriptionText` | (absent) | GRANTED / GRANTED-IN-PART / DENIED / DISMISSED. The field is **analyzed**: `:GRANTED` and `:"GRANTED"` both match 882,323 records (GRANTED plus GRANTED-IN-PART), against 880,459 GRANTED. Matching is case-insensitive (`:denied` = 7,499) | served as is on unfiltered records |
| `decidedPetitionTypeCode` | (absent) | A / B / C / D, exact. Facet counts pair one-to-one with the text: A = GRANTED, B = GRANTED-IN-PART, C = DENIED, D = DISMISSED. `decidedPetitionTypeCode:A` = 880,459 | the `decision_type` filter goes out on this field |
| `decisionPetitionTypeCode` | integer `551` | **string** `"551"`. `q=decisionPetitionTypeCode:551` still works (13,442 records, was 714) | normalised back to the integer in every record; the filter accepts `551` or `"551"` |
| `firstApplicantName` | upper-cased (`APPLE INC.`) | **as written** (`Apple Inc.`). Matching is case-insensitive: `"Apple Inc."` and `"APPLE INC."` both return 2,798 | no change: the filter sends the value as typed, in quotes, and the server does not re-case the returned value |
| `documentBag` | absent from the record; `includeDocuments=true` on the details endpoint answered HTTP 500 since 2026-07 | **present on every record**, search and details alike: the petition's own papers (e.g. `PETDEC` "Petition Decision", `PET.DEC.AUTO` "ePetition Grant Letter"), not the application file wrapper | served on details with `include_documents=True` (`document_metadata_source: "petition_record"`), dropped with `include_documents=False`; the file-wrapper fallback runs only for a record whose own bag is empty |
| `documentBag[].downloadOptionBag` | (wrapper bag only) | one or more options. PDF: `https://api.uspto.gov/api/v1/download/applications/{app}/{docId}.pdf` with `pageTotalQuantity`; also PNG, MS_WORD, XML. An ePetition grant has a **second PDF** option (`/{docId}/files/grantLetter.pdf`) | the document's own `{docId}.pdf` option is chosen first; `pageCount` is backfilled at the top level |
| `allSearchableFields` | (absent) | **new**: every field concatenated with the decision's full OCR text. 24,468 characters on the seed petition (27,612-byte response, against ~2,900 characters before) | dropped from every record |
| `ocrSearchText` | (absent) | **new**: a 500-character OCR snippet | dropped from every record (document text goes through the content tool, which injection-scans it) |
| `lastModifiedDateTime` | the repo's 2024 reference schema lists `lastIngestionDateTime` | present (`2026-10-05T07:59:05` on the seed: records were re-loaded on the day of the change) | passed through |
| `finalPetitionDecisionIndicator` | (absent) | **new**, boolean | passed through on unfiltered records |
| `applicationStatusDescriptionText`, `applicationStatusDate` | (absent) | **new** | passed through on unfiltered records |
| `prosecutionStatusCode` | string in the 2024 reference schema (no recorded payload) | integer (`161`) | passed through |
| `statuteBag` | sentinel `"No statute provided"` seen on the first 3643 record | the sentinel still exists (6,226 records match `statuteBag:"No statute provided"`), but the newest art-unit-3643 records carry no statuteBag at all | no change |

Sample record (seed petition `70a0101b-8dfc-546b-b5a6-aa7e786cbde3`, GET
without `includeDocuments`, index fields shortened here):

```json
{
  "petitionDecisionRecordIdentifier": "70a0101b-8dfc-546b-b5a6-aa7e786cbde3",
  "applicationNumberText": "15344896",
  "decisionPetitionTypeCode": "502",
  "decisionPetitionTypeCodeDescriptionText": "REVIVE AN APPLICATION ABANDONED BY OPAP OR THE TC - UNINTENTIONALLY DELAYED REPLY, NO ADDITIONAL INFORMATION REQUIRED (37 CFR 1.137(A))",
  "decidedPetitionTypeCode": "C",
  "decidedPetitionTypeCodeDescriptionText": "DENIED",
  "finalPetitionDecisionIndicator": true,
  "petitionMailDate": "2023-11-22",
  "decisionDate": "2024-03-22",
  "firstApplicantName": "RodRadar Ltd.",
  "prosecutionStatusCode": 161,
  "ruleBag": ["37 CFR 1.137(a)"],
  "statuteBag": ["35 USC 27"],
  "lastModifiedDateTime": "2026-10-05T07:59:05",
  "documentBag": [{
    "documentCode": "PETDEC",
    "documentIdentifier": "LU79EIOJBLUEX12",
    "documentCodeDescriptionText": "Petition Decision",
    "officialDate": "2024-03-27T18:05:54",
    "downloadOptionBag": [
      {"mimeTypeIdentifier": "PDF", "downloadUrl": "https://api.uspto.gov/api/v1/download/applications/15344896/LU79EIOJBLUEX12.pdf", "pageTotalQuantity": 10},
      {"mimeTypeIdentifier": "PNG", "downloadUrl": "https://api.uspto.gov/api/v1/download/applications/15344896/LU79EIOJBLUEX12/files/media_image1.png"},
      {"mimeTypeIdentifier": "MS_WORD", "downloadUrl": "…/LU79EIOJBLUEX12/files/O.P.%20Petition%20Decision.docx"},
      {"mimeTypeIdentifier": "XML", "downloadUrl": "…/LU79EIOJBLUEX12/xmlarchive"}
    ]
  }],
  "ocrSearchText": "<500 characters of OCR>",
  "allSearchableFields": "15344896 Abandoned -- Failure to Respond … <24,468 characters>"
}
```

## 3. Endpoint behaviour

- **`GET /{id}?includeDocuments=true` now returns the wrong thing.** It answers
  200 with `count: 1113650` and the first 25 records of the whole corpus,
  newest first, none of them the requested petition. Before 2026-10 it
  answered 500 and the server fell back to the application file wrapper. The
  server's download tool, content tool and details-with-documents all read
  `petitionDecisionDataBag[0]` of that answer, so they looked the document up
  in an unrelated petition ("Document LU79EIOJBLUEX12 not found in petition
  70a0101b-…"), and a details lookup of a nonexistent UUID came back as a
  success. The server no longer sends `includeDocuments` (the bag is native),
  and it serves only the record whose identifier was asked for (a 404
  otherwise).
- **`GET /{id}` without the parameter** returns the one record with its
  documentBag, or 404 "No matching records found" for an unknown UUID.
- **Default order is newest decision first** (`decisionDate` descending),
  visible on every search: application 15344896 comes back 2024-03-22,
  2023-10-03, 2023-08-25, 2023-02-07 by decision date, and art unit 3643's first
  record is a 2026-09-17 decision. The request body's
  `sort: [{"field": "petitionMailDate", "order": "asc"}]` works (art unit 3643
  then starts at 2001-10-29). The previous default order could not be
  reconstructed: it was never documented or promised by USPTO, and no
  pre-change payload with more than one record survives.
  The server therefore does not re-sort, and every search tool's description
  now says the order is newest decision first.
- **`rangeFilters`** still works (art unit 3643, `petitionMailDate`
  2015-01-01..2016-12-31: 321 records, all in range; it was 11 on 2026-08-30).
- **Document download**: the native `downloadUrl` answers 302 to
  `data-documents.uspto.gov/redirect/download/...` (a redirect valid for 30
  seconds), which serves the PDF (1,047,302 bytes, `%PDF-1.2`, fetched through
  `FPDClient._download_pdf_for_extraction`). The key-stripping event hook keeps
  the key on that hop because the host is on uspto.gov, as before.

## 4. What the server does now

All in `src/fpd_mcp/api/payload_compat.py` (pure functions) and its call sites:

- records: `decisionPetitionTypeCode` back to an integer; legacy
  `decisionTypeCodeDescriptionText` / `decisionTypeCode` aliases; the two
  index fields dropped; `pageCount` backfilled on every documentBag.
- requests: a projection naming a legacy field also names the new one; the
  `decision_type` filter goes out as `decidedPetitionTypeCode:<A|B|C|D>` (an
  unrecognised value goes out quoted on the text field, so it still comes back
  as an honest zero); a raw `query` clause on `decisionTypeCodeDescriptionText`
  is rewritten to `decidedPetitionTypeCodeDescriptionText`; a petition type
  code is accepted as `551` or `"551"`.
- details (`FPDClient.get_petition_by_id`): no `includeDocuments`; the
  requested record only; the bag dropped when documents were not asked for;
  `document_metadata_source: "petition_record"` on a native bag; the
  file-wrapper fallback only for a record with an empty bag.
- by-application with documents: native bags labelled `petition_record`; the
  wrapper is fetched (once per page) only for records with an empty bag, and
  each such record carries `document_bag_source: "application_file_wrapper"`.
- download, content and proxy routes: one PDF selector
  (`select_pdf_download`): the document's own `{docId}.pdf`, else the first
  PDF option, else the documented URL pattern built from application number
  and identifier.

## 5. Follow-ups

- **Final decisions only.** The tools search the whole 1.1 million record
  corpus by default. The search tools take `final_only=True` to restrict a
  search to the pre-change population (`finalPetitionDecisionIndicator:true`).
- **Response size.** `decision_type="DENIED", limit=100` on the minimal tier
  can serialise to more than the 40,000-character budget now that
  `firstApplicantName` is populated on most rows. The response guard trims
  the page and says so (`_bounds`), and `paging` reports the rows actually
  returned, with `next_offset` at the first row not returned.
