# FPD MCP — Manual End-to-End Test Suite (FastMCP 4.0.1)

> **Tool visibility caveat (2026-09-02):** `defer_loading: false` is advisory
> metadata that each client applies by its own policy, so an expected tool
> being invisible in a given client is not, by itself, a server defect. If a
> tool this suite calls does not appear in the client, record two facts
> separately: whether the server lists it (direct stdio or in-container probe
> of `tools/list`), and that this client did not. A tool the server does not
> list is a server defect and must be reported as one; a tool the server lists
> but the client hides is a client-visibility finding. Never fold one into the
> other. Load-bearing workflow content deliberately also rides in per-tool
> docstrings and return-path notes for exactly this reason.

Run these via Claude Desktop (STDIO) against the migrated server. Tests
marked ⭐ produce identifiers used by later tests. Anchor data was validated
against the live FPD API on 2026-07-04 (counts drift as USPTO adds data —
treat them as "approximately").

> Note on the `includeDocuments=true` upstream outage (first seen
> 2026-07-04, USPTO returns HTTP 500): the server now recovers via the
> application-file-wrapper fallback (`document_metadata_source:
> "application_file_wrapper_fallback"` in the T5 response), so T5, T6, and
> T11 pass end-to-end even while the upstream endpoint errors. Full suite
> re-run 2026-07-19 over stdio: T0-T11 pass (T11 via the Docling tier;
> configure `MISTRAL_API_KEY` or `DOCLING_SERVE_URL` for the OCR
> fallback), T16-T17 pass.

> **⚠ Identifier formats (suite audited 2026-09-02):** `application_number` is
> the APPLICATION serial and is a different namespace from a granted patent
> number. Since patent numbers passed 10,000,000 in mid-2018 the two collide at
> 8 digits, and **this server does not lane-resolve between them:** an 8-digit
> patent number passed as `application_number` returns a clean empty result that
> reads as "no petitions", which is wrong rather than empty. The PFW MCP is the
> crosswalk (`PFW_search_applications_minimal` with `query='patentNumber:<n>'`
> or `query='applicationNumberText:<n>'`). **Audit result:** the only numeric
> identifier in this suite is T4's `13408005`, which is an APPLICATION serial;
> no granted patent number is passed anywhere. Keep it that way, or say which
> namespace a new fixture means.

## Reference anchors

| Anchor | Value | Used by |
|---|---|---|
| Applicant | `Apple` (31 petitions) | T1 |
| Decision type | `DENIED` (7,481) | T2, T8, T9 |
| Balanced combo | art_unit `2128` + type `551` + `DENIED` (=2) | T3 |
| Application | `13408005` (=1 petition); application SERIAL, not a patent number | T4 |
| Petition (download) | `e55bd36d-961f-511e-b72c-b4b1529d67ef`, doc `HY1J6ICXPXXIFW4` | T5, T6 |
| Petition (OCR) | `9b44e6aa-b9fa-59f8-8d73-6c682b5f4426`, doc `MA15BPLNWFYBX96` | T11 |
| Art unit | `2128` (=3 petitions) | T7 |
| 2024 DENIED date range | =239 | T8 |

---

### T0 FPD_get_guidance — guidance loads
```
FPD_get_guidance
{"section": "tools"}
```
**Expect:** sectioned guidance text; no error.

### T1 FPD_Search_petitions_minimal — applicant search ⭐
```
FPD_Search_petitions_minimal
{"applicant_name": "Apple", "limit": 2}
```
**Expect:** `count` = 31, 2 records with the 8 minimal fields. **MCP App
view renders**: petition cards with decision badges; tier badge MINIMAL.

### T2 FPD_Search_petitions_minimal — broader search
```
FPD_Search_petitions_minimal
{"decision_type": "DENIED", "limit": 2}
```
**Expect:** `count` = 7,481. View shows Found 7,481 / Showing 2.

### T3 FPD_Search_petitions_balanced — advanced filters
```
FPD_Search_petitions_balanced
{"art_unit": "2128", "petition_type_code": "551", "decision_type": "DENIED", "limit": 2}
```
**Expect:** `count` = 2; balanced-tier fields (ruleBag, inventionTitle,
groupArtUnitNumber…). View filter pills for Decision/Type when values vary.

### T4 FPD_Search_petitions_by_application
```
FPD_Search_petitions_by_application
{"application_number": "13408005"}
```
**Expect:** `count` = 1.

### T5 FPD_Get_petition_details — with documents ⭐
```
FPD_Get_petition_details
{"petition_id": "e55bd36d-961f-511e-b72c-b4b1529d67ef", "include_documents": true}
```
**Expect:** petition record with `documentBag` containing doc
`HY1J6ICXPXXIFW4`. The upstream `includeDocuments=true` 500 is still live
(re-verified 2026-09-03), so also expect `document_metadata_source:
"application_file_wrapper_fallback"`, `document_metadata_available: true`,
and a `document_metadata_note` that says in words that the bag is the
APPLICATION'S FILE WRAPPER and not a petition bag, carrying the date the
upstream 500 was last observed. The bag holds the whole prosecution history,
so expect non-petition documents (office actions, claims, IDS) in it; that is
correct, not a defect. With `include_documents: false` the petition record
returns without documents.

### T6 FPD_get_document_download — persistent link ⭐
```
FPD_get_document_download
{"petition_id": "e55bd36d-961f-511e-b72c-b4b1529d67ef", "document_identifier": "HY1J6ICXPXXIFW4"}
```
**Expect:** `download_url` is a **persistent link** —
`http://localhost:8081/download/persistent/{24-hex}` (local mode) or the
PFW proxy's `/document/persistent/{hash}` (centralized mode);
`enhanced_filename` like `PET-YYYY-MM-DD_APP-13408005_...pdf`;
`download_id` set; `expires_in_days: 7`. Click the link in a browser:
ERR_ABORTED + the PDF lands in Downloads (no 401 — the hash is the
credential). Passes through the file-wrapper fallback while the upstream
`includeDocuments` outage lasts (verified on prod 2026-09-03).

### T7 FPD_Search_petitions_by_art_unit
```
FPD_Search_petitions_by_art_unit
{"art_unit": "2128", "limit": 5}
```
**Expect:** `count` = 3.

### T8 Temporal analysis — date range
```
FPD_Search_petitions_minimal
{"decision_type": "DENIED", "petition_date_start": "2024-01-01", "petition_date_end": "2024-12-31", "limit": 5}
```
**Expect:** `count` = 239.

### T9 Parameter validation — balanced-only param on minimal tier
```
FPD_Search_petitions_minimal
{"decision_type": "DENIED", "petition_type_code": "551", "limit": 5}
```
**Expect (changed at the FastMCP 3 migration, unchanged on 4.0.1):** a structured validation error naming
`petition_type_code` as an unexpected argument (pre-migration behavior was
silent degradation). The model should retry without the param or switch to
`FPD_Search_petitions_balanced`. No hang, no generic 500.

> DIRECT CALL ONLY (verified 2026-09-02 on FastMCP 4.0.1): this test cannot
> be run through claude.ai, whose client enforces the published
> `additionalProperties: false` schema and refuses to send the unexpected
> argument at all, so the call never reaches the server. That is a PASS at
> an even earlier layer, not a failure. To exercise the server-side error,
> call over stdio or raw HTTP: the server answers `is_error: true` with a
> structured "1 validation error for call[fpd_search_petitions_minimal]"
> body naming the parameter. A tester who cannot make direct calls should
> record T9 as "blocked client-side by schema (expected)".

### T10 Parameter validation — balanced tier accepts the params
```
FPD_Search_petitions_balanced
{"decision_type": "DENIED", "petition_type_code": "551", "limit": 5}
```
**Expect:** normal results (petition_type_code is a balanced-tier param).

### T11 FPD_get_document_content_with_ocr ⭐
```
FPD_get_document_content_with_ocr
{"petition_id": "9b44e6aa-b9fa-59f8-8d73-6c682b5f4426", "document_identifier": "MA15BPLNWFYBX96", "auto_optimize": true}
```
**Expect:** `extracted_content` text; `extraction_method` `pypdf` (native
text layer) or `Mistral OCR (...)`; **progress notifications** appear
during download/OCR.
Docling is the third tier for scanned docs ≤ 25 pages when
`DOCLING_SERVE_URL` is set. Passes through the file-wrapper fallback while
the upstream `includeDocuments` outage lasts.
Also expect a `provenance_note` field (retrieved-text-is-data labeling,
2026-07 provenance posture) on every successful response; an
`injection_scan` annotation appears ONLY if the extracted text is
injection-shaped (kind labels, never matched text) and must be entirely
absent for a normal petition document.

### T12 Downloads panel (MCP App)
After T6: the recent-downloads panel renders next to the tool result with
the new entry; the Download PDF button opens the persistent link via the
system browser.

### T13 /downloads page + highlight
Open `http://localhost:8081/downloads?highlight={download_id from T6}` in
a browser. **Expect:** FPD-branded page, the highlighted row scrolls into
view, Download PDF works, list refreshes every 5s.

### T15 Centralized proxy mode
With `CENTRALIZED_PROXY_URL=http://localhost:8080` (local PFW proxy
running; in production use the deployment's published PFW proxy base):
re-run T6. **Expect:** `proxy_info.mode: "centralized"`; `download_url`
is a PFW `/document/persistent/{hash}` URL that streams the PDF in a
browser. Requires PFW ≥ commit 311dc2a (registration returns persistent
links) and the shared `INTERNAL_AUTH_SECRET` on both sides.

### T16 HTTP transport mode
`FASTMCP_TRANSPORT=http FASTMCP_PORT=8005 INTERNAL_AUTH_SECRET=…`:
- `GET /health` → 200 OK (no auth)
- `POST /mcp` with wrong `x-api-key` → 401 + a "HTTP auth failed" log
  event (never the key)
- `POST /mcp` without `text/event-stream` in Accept → 401 (claude.ai probe)
- No secret set → server refuses to start
- No uvicorn access-log lines (persistent-link paths embed credentials)

### T17 Logging content-minimization spot check
Run T1 with `LOG_LEVEL=DEBUG`. **Expect:** stderr/log files contain
`Search request shape: query_chars=…` — never the applicant name or query
text; any persistent-link hash appears truncated (`649b4597...`) or as
`[LINK_HASH]`.

### T18 `_bounds.items_total` agrees with `paging.total`
```
FPD_Search_petitions_balanced
{"query": "ruleBag:\"37 CFR 1.137\"", "limit": 50}
```
**Expect:** `paging.total` is the number of matching petitions (53 on
2026-09-03, and it grows). If the response also carries `_bounds` (it does
whenever the guard shed rows to fit the budget), `_bounds.items_total`
carries the SAME figure. The two disagreeing is a defect: before
2026-09-03 this call returned `paging.total` 53 alongside
`_bounds.items_total` 50, the page the guard had been handed.
`_bounds.items_returned` is smaller than both, and correctly counts the
records actually present in the response.
