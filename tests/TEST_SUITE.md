# FPD MCP — Manual End-to-End Test Suite (FastMCP 3.0)

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

## Reference anchors

| Anchor | Value | Used by |
|---|---|---|
| Applicant | `Apple` (~31 petitions) | T1 |
| Decision type | `DENIED` (~7,473) | T2, T8, T9 |
| Balanced combo | art_unit `2128` + type `551` + `DENIED` (=2) | T3 |
| Application | `13408005` (=1 petition) | T4 |
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

### T1 Search_petitions_minimal — applicant search ⭐
```
Search_petitions_minimal
{"applicant_name": "Apple", "limit": 2}
```
**Expect:** `count` ≈ 31, 2 records with the 8 minimal fields. **MCP App
view renders**: petition cards with decision badges; tier badge MINIMAL.

### T2 Search_petitions_minimal — broader search
```
Search_petitions_minimal
{"decision_type": "DENIED", "limit": 2}
```
**Expect:** `count` ≈ 7,473. View shows Found ~7,473 / Showing 2.

### T3 Search_petitions_balanced — advanced filters
```
Search_petitions_balanced
{"art_unit": "2128", "petition_type_code": "551", "decision_type": "DENIED", "limit": 2}
```
**Expect:** `count` = 2; balanced-tier fields (ruleBag, inventionTitle,
groupArtUnitNumber…). View filter pills for Decision/Type when values vary.

### T4 Search_petitions_by_application
```
Search_petitions_by_application
{"application_number": "13408005"}
```
**Expect:** `count` = 1.

### T5 Get_petition_details — with documents ⭐
```
Get_petition_details
{"petition_id": "e55bd36d-961f-511e-b72c-b4b1529d67ef", "include_documents": true}
```
**Expect:** petition record with `documentBag` containing doc
`HY1J6ICXPXXIFW4`. ⚠️ Currently blocked by the upstream
`includeDocuments=true` 500 — with `include_documents: false` the petition
record returns fine.

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
credential). ⚠️ Blocked by the same upstream outage until USPTO fixes
`includeDocuments`.

### T7 Search_petitions_by_art_unit
```
Search_petitions_by_art_unit
{"art_unit": "2128", "limit": 5}
```
**Expect:** `count` = 3.

### T8 Temporal analysis — date range
```
Search_petitions_minimal
{"decision_type": "DENIED", "petition_date_start": "2024-01-01", "petition_date_end": "2024-12-31", "limit": 5}
```
**Expect:** `count` = 239.

### T9 Parameter validation — balanced-only param on minimal tier
```
Search_petitions_minimal
{"decision_type": "DENIED", "petition_type_code": "551", "limit": 5}
```
**Expect (changed under FastMCP 3):** a structured validation error naming
`petition_type_code` as an unexpected argument (pre-migration behavior was
silent degradation). The model should retry without the param or switch to
`Search_petitions_balanced`. No hang, no generic 500.

### T10 Parameter validation — balanced tier accepts the params
```
Search_petitions_balanced
{"decision_type": "DENIED", "petition_type_code": "551", "limit": 5}
```
**Expect:** normal results (petition_type_code is a balanced-tier param).

### T11 FPD_get_document_content_with_mistral_ocr ⭐
```
FPD_get_document_content_with_mistral_ocr
{"petition_id": "9b44e6aa-b9fa-59f8-8d73-6c682b5f4426", "document_identifier": "MA15BPLNWFYBX96", "auto_optimize": true}
```
**Expect:** `extracted_content` text; `extraction_method` PyPDF2 (free) or
Mistral OCR; **progress notifications** appear during download/OCR.
Docling is the third tier for scanned docs ≤ 25 pages when
`DOCLING_SERVE_URL` is set. ⚠️ Blocked by the upstream outage.
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

### T14 URL elicitation (Claude Desktop only)
After T6 in Claude Desktop: an elicitation prompt offers to open the FPD
downloads page. **Accept** → browser opens `/downloads?highlight=…`;
**Decline** → normal JSON result regardless. On clients without URL
elicitation (claude.ai) the prompt must NOT appear and the tool must not
hang (capability gate).

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
