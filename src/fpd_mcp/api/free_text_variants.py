"""Free-text variants of a documentBag entry.

Copied 2026-10-07 from uspto_pfw_mcp ``api/free_text_variants.py`` (PFW is the
source; change it there and re-copy, the only local edit is the logger import).
FPD petition decisions carry the same variants since USPTO's 2026-10 payload
change: a PETDEC's downloadOptionBag lists PDF, MS_WORD (``.../files/<name>.docx``),
PNG and XML (``.../xmlarchive``, a tar holding ``uspat:OutgoingDocument``), probed
live on petition 190d9855-9216-58ae-b37d-c838d16f441e (application 16/724,244).

PFW's original docstring follows.

Free-text variants of a documentBag entry (2026-08-25).

``PFW_get_document_content_with_ocr`` used to read only the rasterized IFW PDF
render, so a desktop user paid Mistral OCR for text the ODP API already serves
for free: the ``downloadOptionBag`` of USPTO-authored papers (office actions,
reexam orders / NIRCs, petition decisions) carries a ``.docx`` and an
``xmlarchive`` variant with the full text, incoming e-filed papers (CLM, REM,
IDS, SPEC) carry an ``xmlarchive`` holding the USPTO's own OCR or the filed
XML, and as-uploaded filings (``.../files/<name>.pdf``) keep their native text
layer. This module turns those variants into text. Stdlib + defusedxml only.

Live-probed shapes (2026-08-25, ODP ``/applications/{n}/documents``):

- ``mimeTypeIdentifier`` is ``PDF`` | ``MS_WORD`` | ``XML`` | ``PNG``.
- The IFW render is ``.../download/applications/<app>/<docid>.pdf``; every
  other variant lives under ``.../<docid>/files/<name>`` or ``.../<docid>/xmlarchive``.
- ``xmlarchive`` is an uncompressed TAR whose member path is
  ``<app>/<docid>/<name>.xml`` (``uspat:OutgoingDocument``,
  ``uspat:IncomingDocument``, ``uspat:ClaimsDocument`` roots, ST.96-style).
- One fetch was observed returning ANOTHER control number's CLM (90/020,162
  inside a 90/016,076 document); an identical re-fetch was correct. Every
  archive is therefore checked against the requested application — the member
  path's first component AND every ``ApplicationNumberText`` element — and a
  mismatch rejects the variant (``VariantMismatchError``) so the caller falls
  through to the PDF tiers instead of serving the wrong file.
"""

import io
import re
import tarfile
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse

# defusedxml: hardens against XXE / entity-expansion in USPTO-served XML (audit L12)
import defusedxml.ElementTree as ET

from ..shared.unified_logging import get_logger

logger = get_logger(__name__)

#: ``extraction_method`` values reported for the free variants.
METHOD_DOCX = "docx variant"
METHOD_XMLARCHIVE_OCR = "xmlarchive (USPTO OCR)"
METHOD_XMLARCHIVE_XML = "xmlarchive (USPTO XML)"
METHOD_UPLOADED_PDF = "as-uploaded pdf text layer"

#: Archive members larger than this are skipped rather than inflated in memory.
_MAX_MEMBER_BYTES = 50_000_000

#: Aggregate ceilings for one archive. Per-member alone is not a bound: a zip
#: bomb is many small members, and the declared size a zip header reports is
#: not what decompresses out of it (audits M-18, L-19).
_MAX_ARCHIVE_BYTES = 200_000_000
_MAX_ARCHIVE_MEMBERS = 5_000

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_MC_NS = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"

#: USPTO XML subtrees that are not document text: the metadata block (codes,
#: dates, the application number — collected separately for verification) and
#: the per-page header/footer bag (repeats "Application/Control Number ... Page N").
_XML_SKIP_SUBTREES = frozenset({"DocumentMetadata", "BoundaryDataBag"})
_XML_BLOCK_TAGS = frozenset({
    "P", "Heading", "LI", "OL", "UL", "Table", "DataTable", "TableRow", "Br",
    "Claim", "ClaimText", "FormParagraph", "GeneralText", "FormPageHeader",
    "FormPageBody", "FormPageFooter",
})
_XML_CELL_TAGS = frozenset({"TableDataCell", "TableHeaderCell"})
#: Amendment markup: insertions/deletions are kept verbatim but delimited, so
#: amended claim text does not collapse into an unreadable merge.
_XML_MARK_TAGS = {"Ins": ("<ins>", "</ins>"), "Del": ("<del>", "</del>")}

_APP_NUMBER_RE = re.compile(r"\d[\d,/]*\d")


class VariantMismatchError(ValueError):
    """The variant carries a different application/control number than requested."""


class VariantEmptyError(ValueError):
    """The variant holds no usable text (e.g. an SVG-only archive)."""


# ---------------------------------------------------------------------------
# downloadOptionBag classification
# ---------------------------------------------------------------------------

def classify_download_options(options) -> Dict[str, List[Dict[str, Any]]]:
    """Bucket a ``downloadOptionBag`` into ``docx`` / ``xmlarchive`` /
    ``uploaded_pdf`` / ``render_pdf`` by mime type and URL shape. Images and
    anything unrecognized are dropped."""
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "docx": [], "xmlarchive": [], "uploaded_pdf": [], "render_pdf": [],
    }
    for option in options or []:
        if not isinstance(option, dict):
            continue
        path = unquote(urlparse(option.get("downloadUrl") or "").path).lower()
        mime = (option.get("mimeTypeIdentifier") or "").upper()
        if mime == "MS_WORD" or path.endswith(".docx"):
            buckets["docx"].append(option)
        elif mime == "XML" or path.endswith("/xmlarchive"):
            buckets["xmlarchive"].append(option)
        elif mime == "PDF" or path.endswith(".pdf"):
            buckets["uploaded_pdf" if "/files/" in path else "render_pdf"].append(option)
    return buckets


# ---------------------------------------------------------------------------
# Application-number verification
# ---------------------------------------------------------------------------

def normalize_application_number(value) -> Optional[str]:
    """``'90/016,076\\tPage 2'`` -> ``'90016076'``; ``None`` when no number is present."""
    if value is None:
        return None
    match = _APP_NUMBER_RE.search(str(value))
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(0))
    return digits or None


def check_application_number(candidates: List[str], requested: str) -> Tuple[bool, List[str]]:
    """Return ``(verified, mismatches)``. ``verified`` is True only when at
    least one candidate was found and all of them equal the requested number;
    ``mismatches`` lists the distinct candidates that differ."""
    wanted = normalize_application_number(requested)
    seen = [c for c in (normalize_application_number(c) for c in candidates) if c]
    mismatches = sorted({c for c in seen if c != wanted})
    return bool(seen) and not mismatches, mismatches


def _local(tag) -> str:
    tag = tag if isinstance(tag, str) else ""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _normalize_text(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        line = re.sub(r"[  ]*\t[ \t ]*", "\t", line)
        line = re.sub(r"[  ]{2,}", " ", line).strip()
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


# ---------------------------------------------------------------------------
# .docx (OOXML zip)
# ---------------------------------------------------------------------------

def _docx_walk(el, parts: List[str]) -> None:
    tag = el.tag
    if tag == _MC_NS + "Fallback":
        return  # duplicate rendering of an AlternateContent Choice (text boxes)
    if tag == _W_NS + "t":
        parts.append(el.text or "")
    elif tag == _W_NS + "tab":
        parts.append("\t")
    elif tag in (_W_NS + "br", _W_NS + "cr", _W_NS + "p"):
        parts.append("\n")
    for child in el:
        _docx_walk(child, parts)


def _docx_part_text(xml_bytes: bytes) -> str:
    parts: List[str] = []
    _docx_walk(ET.fromstring(xml_bytes), parts)
    return _normalize_text("".join(parts))


def _docx_app_number_candidates(custom_xml: bytes) -> List[str]:
    """USPTO-authored .docx files carry ``FormattedApplicationNumber`` in
    ``docProps/custom.xml`` (observed: ``90/016,076``)."""
    candidates: List[str] = []
    try:
        root = ET.fromstring(custom_xml)
    except Exception:
        return candidates
    for prop in root:
        if prop.get("name") == "FormattedApplicationNumber":
            candidates.extend((child.text or "") for child in prop)
    return candidates


def _read_capped(zf: "zipfile.ZipFile", name: str) -> bytes:
    """Read one archive member, refusing to decompress past the cap.

    The docx path called ``zf.read()`` on three members with no ceiling; a
    small archive can declare and deliver an arbitrarily large part
    (audit M-18, CWE-409). The DECLARED size is checked first because it is
    free, then the actual read is bounded, because the two can disagree.
    """
    info = zf.getinfo(name)
    if info.file_size > _MAX_MEMBER_BYTES:
        raise VariantEmptyError(
            f"archive member {name} declares {info.file_size} bytes, "
            f"over the {_MAX_MEMBER_BYTES}-byte cap"
        )
    with zf.open(name) as handle:
        data = handle.read(_MAX_MEMBER_BYTES + 1)
    if len(data) > _MAX_MEMBER_BYTES:
        raise VariantEmptyError(
            f"archive member {name} decompressed past the "
            f"{_MAX_MEMBER_BYTES}-byte cap"
        )
    return data


def extract_docx(data: bytes, requested_app_number: str) -> Dict[str, Any]:
    """Text of a .docx variant. Raises ``VariantMismatchError`` when its
    application-number property names another application, ``VariantEmptyError``
    when it holds no text, ``zipfile.BadZipFile`` when it is not a docx."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = set(zf.namelist())
        if "word/document.xml" not in names:
            raise VariantEmptyError("docx has no word/document.xml part")
        text = _docx_part_text(_read_capped(zf, "word/document.xml"))
        footnotes = (
            _docx_part_text(_read_capped(zf, "word/footnotes.xml"))
            if "word/footnotes.xml" in names else ""
        )
        candidates = (
            _docx_app_number_candidates(_read_capped(zf, "docProps/custom.xml"))
            if "docProps/custom.xml" in names else []
        )
    verified, mismatches = check_application_number(candidates, requested_app_number)
    if mismatches:
        raise VariantMismatchError(
            f"docx variant names application {', '.join(mismatches)}, not {requested_app_number}"
        )
    if footnotes:
        text = f"{text}\n\n{footnotes}" if text else footnotes
    if not text:
        raise VariantEmptyError("docx variant holds no text")
    return {
        "text": text,
        "extraction_method": METHOD_DOCX,
        "application_number_verified": verified,
    }


# ---------------------------------------------------------------------------
# xmlarchive (tar or zip of USPTO ST.96-style XML)
# ---------------------------------------------------------------------------

def _read_member_capped(open_member, declared_size: int):
    """One member's bytes, or None when it busts the per-member cap.

    The declared size is checked first because it is free, and the read is
    bounded too because a zip header's declared size and what decompresses
    out of it can disagree (audit L-19).
    """
    if declared_size > _MAX_MEMBER_BYTES:
        return None
    raw = open_member.read(_MAX_MEMBER_BYTES + 1)
    return None if len(raw) > _MAX_MEMBER_BYTES else raw


def _zip_members(data: bytes):
    """(name, bytes) for each acceptable zip member."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            with zf.open(info) as handle:
                raw = _read_member_capped(handle, info.file_size)
            if raw is not None:
                yield info.filename, raw


def _tar_members(data: bytes):
    """(name, bytes) for each acceptable tar member."""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        for info in tf.getmembers():
            if not info.isfile():
                continue
            handle = tf.extractfile(info)
            if handle is None:
                continue
            raw = _read_member_capped(handle, info.size)
            if raw is not None:
                yield info.name, raw


def _archive_members(data: bytes) -> List[Tuple[str, bytes]]:
    """Members of a zip or tar, under a per-member AND an aggregate budget.

    The per-member cap alone was not a bound (audit L-19): it was applied to
    the DECLARED size only, and many small members add up. Over-budget stops
    the walk rather than raising, so a partly-readable archive still yields
    the members it got to — the caller treats an empty list as "no variant".
    """
    members: List[Tuple[str, bytes]] = []
    total = 0
    source = _zip_members(data) if data[:2] == b"PK" else _tar_members(data)

    for name, raw in source:
        total += len(raw)
        if total > _MAX_ARCHIVE_BYTES or len(members) >= _MAX_ARCHIVE_MEMBERS:
            logger.warning(
                "xmlarchive exceeded its budget (%d bytes / %d members); "
                "stopping the walk", total, len(members),
            )
            break
        members.append((name, raw))

    return members


def _looks_like_svg(name: str, raw: bytes) -> bool:
    return name.lower().endswith(".svg") or b"<svg" in raw[:2048].lower()


def _xml_walk(el, parts: List[str]) -> None:
    name = _local(el.tag)
    if name in _XML_SKIP_SUBTREES:
        return
    block = name in _XML_BLOCK_TAGS
    if block:
        parts.append("\n")
    elif name in _XML_CELL_TAGS:
        parts.append("\t")
    open_mark, close_mark = _XML_MARK_TAGS.get(name, ("", ""))
    parts.append(open_mark)
    if el.text:
        parts.append(el.text)
    for child in el:
        _xml_walk(child, parts)
        if child.tail:
            parts.append(child.tail)
    parts.append(close_mark)
    if block:
        parts.append("\n")


def _xml_app_number_candidates(root) -> List[str]:
    candidates = []
    for el in root.iter():
        if _local(el.tag) != "ApplicationNumberText":
            continue
        electronic = next((v for k, v in el.attrib.items() if _local(k) == "electronicText"), None)
        candidates.append(electronic if electronic else (el.text or ""))
    return candidates


def _member_app_number(name: str) -> Optional[str]:
    first = name.strip("/").split("/", 1)[0]
    return first if first.isdigit() else None


def extract_xmlarchive(data: bytes, requested_app_number: str) -> Dict[str, Any]:
    """Text of an ``xmlarchive`` variant with the application-number check
    described in the module docstring. SVG (image) members are skipped."""
    texts: List[str] = []
    candidates: List[str] = []
    saw_svg = False
    ocr_markup = False
    for name, raw in _archive_members(data):
        member_app = _member_app_number(name)
        if member_app:
            candidates.append(member_app)
        if _looks_like_svg(name, raw):
            saw_svg = True
            continue
        try:
            root = ET.fromstring(raw)
        except Exception:
            logger.info("xmlarchive member is not parseable XML; skipped")
            continue
        candidates.extend(_xml_app_number_candidates(root))
        ocr_markup = ocr_markup or any(_local(e.tag) == "OCRConfidenceData" for e in root.iter())
        parts: List[str] = []
        _xml_walk(root, parts)
        text = _normalize_text("".join(parts))
        if text:
            texts.append(text)
    verified, mismatches = check_application_number(candidates, requested_app_number)
    if mismatches:
        raise VariantMismatchError(
            f"xmlarchive names application {', '.join(mismatches)}, not {requested_app_number}"
        )
    if not texts:
        raise VariantEmptyError(
            "xmlarchive holds no text" + (" (image-only SVG members)" if saw_svg else "")
        )
    return {
        "text": "\n\n".join(texts),
        "extraction_method": METHOD_XMLARCHIVE_OCR if ocr_markup else METHOD_XMLARCHIVE_XML,
        "application_number_verified": verified,
    }
