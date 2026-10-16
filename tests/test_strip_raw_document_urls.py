"""CR-59/MCP-9 (review 2026-09-28): documentBag must never carry the raw,
API-key-requiring downloadUrl, on the petition-details path or the
by-application search with include_documents=True."""
from fpd_mcp.tools.petitions import _strip_raw_document_urls


def _row(n_docs: int) -> dict:
    return {
        "petitionDecisionRecordIdentifier": "p-1",
        "documentBag": [
            {
                "documentIdentifier": f"DOC{i}",
                "downloadOptionBag": [{"downloadUrl": "https://api.uspto.gov/raw"}],
            }
            for i in range(n_docs)
        ],
    }


def test_strips_every_download_option_bag():
    result = {"petitionDecisionDataBag": [_row(2), _row(1)]}
    out = _strip_raw_document_urls(result)
    docs = [d for r in out["petitionDecisionDataBag"] for d in r["documentBag"]]
    assert len(docs) == 3
    assert all("downloadOptionBag" not in d for d in docs)
    assert all(d["documentIdentifier"].startswith("DOC") for d in docs)
    assert "api.uspto.gov/raw" not in repr(out)


def test_tolerates_rows_without_documents():
    result = {"petitionDecisionDataBag": [{"petitionDecisionRecordIdentifier": "p-2"}, "junk"]}
    assert _strip_raw_document_urls(result) == result
    assert _strip_raw_document_urls({"error": "x"}) == {"error": "x"}
