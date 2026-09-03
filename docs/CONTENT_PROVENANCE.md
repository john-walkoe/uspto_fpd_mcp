# Content provenance and retrieved-text handling

This document is the written answer to the security-questionnaire line that asks
"how do you sanitize retrieved content before passing it to an AI model?" It
records what the USPTO FPD MCP does, what it deliberately does not do, and why.
(The labeling implementation lives in `src/fpd_mcp/shared/injection_scan.py`
(`RETRIEVED_TEXT_NOTE` and the detection-only scanner) and the server
instructions' provenance-posture paragraph in `src/fpd_mcp/main.py`.)

## Source corpus

Every document served by this system originates from the USPTO Final Petition
Decisions (FPD) API at `api.uspto.gov`: petitions filed with the Office,
Director's final petition decisions, and their supporting documents. Filers are
identified parties in prosecution matters and the documents carry legal effect.
This is a curated regulatory corpus, not the open web: there is no anonymous
user-generated content, no crawled third-party pages, and no open submissions
in the retrieval path. "Curated" is not "trusted," however: a petition and its
exhibits contain arbitrary petitioner-drafted content, and a party can word its
own filings to steer how an automated assistant characterizes them.

## What we deliberately do NOT do: strip or rewrite document text

Legal research depends on verbatim fidelity. A "sanitization" pass that removes
or rewrites token sequences from a petition or a Director's decision would
corrupt the exact language attorneys are retrieving — CFR citations, statutory
references, the Director's reasoning. Document text is therefore served
verbatim, with provenance attached, and is never mutated in the name of
injection defense. This includes the OCR path: for scanned, image-filed
documents the extraction pipeline (pypdf, then Mistral OCR, then self-hosted
Docling) performs faithful text extraction of the page images, and that
extraction output is served as-is. No tier of the pipeline summarizes,
paraphrases, or filters document content.

## What we do instead: structured, provenance-aware interfaces

1. **Data/instruction separation by labeling.** The text-bearing tool
   (`FPD_get_document_content_with_ocr`) attaches a machine-readable
   `provenance_note` to every successful response stating that the extracted
   text is quoted data, not instructions, and the server-level instructions
   direct the consuming model to report instruction-like language found inside
   retrieved text rather than act on it. Petitioner- or office-drafted
   characterizations are to be presented as attributed positions, not
   established fact.
2. **Detection-only injection annotation.** Extracted text is passed through a
   stdlib-only, detection-only scanner (`shared/injection_scan.py`) covering
   instruction-override, prompt-extraction, and encoding-evasion language plus
   invisible-Unicode steganography density. On a hit the response carries an
   `injection_scan` annotation naming the petition, document identifier, and
   the kind of pattern found — never the matched text — and the annotation is
   absent entirely when the text is clean. The text itself is returned
   untouched either way.
3. **No generative model in the retrieval path.** The petition search and
   details tools return structured metadata fields from the USPTO API. Content
   extraction uses OCR/text-extraction engines only (pypdf, Mistral OCR,
   Docling); no large language model summarizes or rewrites retrieved content
   anywhere in the serving path.
4. **Content-minimizing logging.** Logs record operational flow metadata only —
   tool, status, counts, error class, public identifiers — never query text,
   document/OCR content, tokens, or link hashes beyond a truncated prefix. A
   sink-level `SanitizingFilter` (`shared/log_sanitizer.py`, attached to every
   handler in `config/log_config.py`) is the guarantee behind call-site
   discipline. Scanner output follows the same rule: kind labels and document
   identifiers may be logged, matched text never is.
5. **Codebase-hygiene scanning (distinct layer).** The `.security/` pre-commit
   detectors scan this repository's own source tree for injection-shaped
   strings at commit time. That commit-time layer guards the codebase; the
   runtime scanner above annotates retrieved corpus content at tool-call time.
   The two are complementary, not substitutes.

## Residual-risk statement

Prompt-injection risk in this product reduces to: a petition document or
exhibit contains text crafted to influence a downstream AI assistant. The
controls above ensure such text (a) reaches the assistant clearly labeled as
quoted document content with a provenance note, (b) is annotated by kind when
it is injection-shaped, and (c) is always traceable to its source petition and
document identifier for human verification. We consider stripping-based
defenses inappropriate for a corpus whose value is verbatim legal text, and
labeling-plus-detection the correct control for this threat model.
