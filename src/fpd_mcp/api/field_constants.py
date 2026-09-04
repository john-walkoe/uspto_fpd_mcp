"""
USPTO Final Petition Decisions API Field Constants

This module defines all USPTO FPD API field names as constants to eliminate
magic strings throughout the codebase and provide a single source of truth.

Based on USPTO Open Data Portal API - Final Petition Decisions endpoint.

PROVENANCE OF THE FIELD NAMES BELOW
-----------------------------------
Verified: 2026-08-21, re-probed 2026-08-30
Probe:    FPD_Search_petitions_minimal against
          https://api.uspto.gov/api/v1/petition/decisions (live, this repo's
          own client), plus the earlier live probes dated inline in
          api/fpd_client.py and tools/petitions.py.
Baseline observed:
  - ~7,500 petition decision records across petitionMailDate
    1990-01-01..today (the whole date window returns the same count as the
    unfiltered corpus, so that IS the corpus size). The corpus GROWS - it was
    7,473 on 2026-08-21 and 7,489 on 2026-08-30 - so treat any count written
    down here as a floor, never as a current fact, and never serve one in a
    tool response.
  - decisionTypeCodeDescriptionText is overwhelmingly 'DENIED', but not
    exclusively: on 2026-08-30 the corpus held 7,481 DENIED, 6 DISMISSED and
    2 GRANTED. All three values in PetitionRedFlags below are LIVE. An
    earlier note in this file claimed the corpus was DENIED-only on the
    strength of a single 2026-08-21 GRANTED probe returning 0; that claim was
    wrong by 2026-08-30 and had been propagated into two tool docstrings and
    a served string. Rare is not absent.
  - petitionMailDate values reach back to at least 2005; this is not a
    recent-only corpus.
  - The API OMITS null fields rather than returning them as null. Two of the
    eight minimal fields (patentNumber, firstApplicantName) were absent from
    both sampled records. A missing field is normal sparsity, NOT a wrong
    field name - do not "fix" a field name because a record lacks it.
  - decisionPetitionTypeCode vocabulary as OBSERVED (probed 2026-08-30,
    extended 2026-09-03; USPTO's own description text, typos included). This
    list is not exhaustive and cannot be: USPTO publishes no enumerable
    vocabulary, so a code absent from it is simply a code no probe has
    returned yet. 562 and 529 were both missing here until 2026-09-03 while
    live on 37 CFR 1.137 records. 551 is NOT revival - it is the single
    largest class in the corpus and it is PTA correction:
      501       TO REVIVE AN ABANDONED APPLICATION - UNAVOIDABLE DELAY
                (37 CFR 1.137(a))
      502       REVIVE AN APPLICATION ABANDONED BY OPAP OR THE TC -
                UNINTENTIONALLY DELAYED REPLY (37 CFR 1.137(b))
      503       FOR SUSPENSION OR WAIVER OF A RULE (37 CFR 1.183)
      504       TO INVOKE SUPERVISORY AUTHORITY RE - PATENT EXAMINING
                (37 CFR 1.181; also the code restriction petitions under
                37 CFR 1.144 arrive under)
      515       TO INVOKE SUPERVISORY AUTHORITY - RE NON-PATENT EXAMINING
      519 / 520 Rule 1.182 matters
      525       TO WITHDRAW A HOLDING OF ABANDONMENT
      529       To Withdraw A Holding of Abandonment in Pre-Exam Status
                (probed 2026-09-03; USPTO writes this one in mixed case, not
                the upper case the rest of the table uses. It is the
                pre-examination counterpart of 525 and carries
                37 CFR 1.137(b) in its ruleBag, which is why a revival
                filter finds it)
      550 / 551 CORRECTION OF PATENT TERM ADJUSTMENT VALUE (before issue /
                after issue; 714 records of 551)
      562       REVIVE AN APPLICATION ABANDONED BY OPAP OR THE TC -
                UNINTENTIONALLY DELAYED REPLY, ADDITIONAL INFORMATION
                REQUIRED (37 CFR 1.137(A))
    '181' and '182' are CFR rule numbers, not type codes - querying either as
    decisionPetitionTypeCode returns HTTP 404. A revival can arrive under
    several codes - one ruleBag:"37 CFR 1.137" probe returned six distinct
    ones (502, 503, 504, 525, 529, 562) - so the dependable filter for a
    CFR-defined petition class is a ruleBag clause, not a type code.
  - technologyCenter and groupArtUnitNumber are stored as FOUR digits
    ('3600', '1600'; plus the non-numeric 'PFMU'). A two-digit prefix such as
    '21' matches nothing.
  - businessEntityStatusCategory values seen: 'Regular Undiscounted',
    'Small', 'Micro'. There is no 'Large' and no bare 'Undiscounted'.
  - prosecutionStatusCodeDescriptionText values seen: 'Patented' (the bare
    word, not 'Patented Case'), 'During examination', 'After payment of issue
    fee', 'Abandoned', 'No status provided', 'Expired patent', 'Appeal',
    'Terminated'.
  - Range filters (dates, numbers) go in the POST body under `rangeFilters`,
    as {field, valueFrom, valueTo}. The `filters` key rejects that object
    with HTTP 400 and no detailedMessage.
  - The pagination limit ceiling is 100. A limit of 200 answers HTTP 400
    "Requested page limit exceeds allowed limit 100".
Not probed: whether the commented-out candidate fields in field_configs.yaml
exist on the endpoint. They are carried as user-customizable options, not as
verified-present fields.
"""


class FPDFields:
    """
    Constants for USPTO Final Petition Decisions API field names.

    These constants represent the exact field names used by the USPTO API.
    Use these instead of hardcoded strings to enable:
    - IDE autocomplete
    - Easier refactoring
    - Catching typos at development time
    """

    # === TOP-LEVEL FIELDS ===
    PETITION_DECISION_DATA_BAG = "petitionDecisionDataBag"

    # === CORE IDENTIFICATION FIELDS ===
    PETITION_DECISION_RECORD_IDENTIFIER = "petitionDecisionRecordIdentifier"  # UUID
    APPLICATION_NUMBER_TEXT = "applicationNumberText"  # Links to PFW MCP
    PATENT_NUMBER = "patentNumber"  # Links to PTAB MCP

    # === APPLICANT/INVENTOR FIELDS ===
    FIRST_APPLICANT_NAME = "firstApplicantName"
    INVENTOR_BAG = "inventorBag"
    CUSTOMER_NUMBER = "customerNumber"
    FIRST_INVENTOR_TO_FILE_INDICATOR = "firstInventorToFileIndicator"  # AIA indicator

    # === DECISION FIELDS ===
    DECISION_TYPE_CODE_DESCRIPTION_TEXT = "decisionTypeCodeDescriptionText"  # GRANTED/DENIED/DISMISSED
    PETITION_MAIL_DATE = "petitionMailDate"  # When petition filed
    DECISION_DATE = "decisionDate"  # When Director decided
    DECISION_MAIL_DATE = "decisionMailDate"  # When decision mailed
    FINAL_DECIDING_OFFICE_NAME = "finalDecidingOfficeName"  # Deciding office

    # === PETITION TYPE FIELDS ===
    DECISION_PETITION_TYPE_CODE = "decisionPetitionTypeCode"  # Type code (551, etc.)
    DECISION_PETITION_TYPE_CODE_DESCRIPTION_TEXT = "decisionPetitionTypeCodeDescriptionText"

    # === CLASSIFICATION FIELDS ===
    GROUP_ART_UNIT_NUMBER = "groupArtUnitNumber"  # Art unit (→ PFW cross-ref)
    TECHNOLOGY_CENTER = "technologyCenter"  # TC

    # === STATUS FIELDS ===
    PROSECUTION_STATUS_CODE = "prosecutionStatusCode"
    PROSECUTION_STATUS_CODE_DESCRIPTION_TEXT = "prosecutionStatusCodeDescriptionText"
    BUSINESS_ENTITY_STATUS_CATEGORY = "businessEntityStatusCategory"  # Small / Micro / Regular Undiscounted

    # === LEGAL CONTEXT FIELDS (ARRAYS) ===
    PETITION_ISSUE_CONSIDERED_TEXT_BAG = "petitionIssueConsideredTextBag"  # Issues raised
    RULE_BAG = "ruleBag"  # CFR rules cited (e.g., "37 CFR 1.137")
    STATUTE_BAG = "statuteBag"  # Statutes cited

    # === COURT INFORMATION ===
    COURT_ACTION_INDICATOR = "courtActionIndicator"  # Boolean
    ACTION_TAKEN_BY_COURT_NAME = "actionTakenByCourtName"

    # === INVENTION DETAILS ===
    INVENTION_TITLE = "inventionTitle"

    # === METADATA ===
    LAST_INGESTION_DATE_TIME = "lastIngestionDateTime"  # Data freshness

    # === DOCUMENT FIELDS ===
    DOCUMENT_BAG = "documentBag"
    DOCUMENT_IDENTIFIER = "documentIdentifier"
    DOCUMENT_CODE = "documentCode"
    DOCUMENT_CODE_DESCRIPTION_TEXT = "documentCodeDescriptionText"
    DOCUMENT_FILE_NAME = "documentFileName"
    PAGE_COUNT = "pageCount"

    # === DOWNLOAD FIELDS ===
    DOWNLOAD_OPTION_BAG = "downloadOptionBag"
    MIME_TYPE_IDENTIFIER = "mimeTypeIdentifier"  # PDF, etc.
    DOWNLOAD_URL = "downloadUrl"
    PAGE_TOTAL_QUANTITY = "pageTotalQuantity"


class QueryFieldNames:
    """
    Field names as they appear in Lucene/search queries.

    Use these for building search queries with convenience parameters.
    """
    # Core search fields
    APPLICATION_NUMBER = "applicationNumberText"
    PATENT_NUMBER = "patentNumber"
    APPLICANT_NAME = "firstApplicantName"

    # Classification search
    ART_UNIT = "groupArtUnitNumber"
    TECHNOLOGY_CENTER = "technologyCenter"

    # Date search
    PETITION_MAIL_DATE = "petitionMailDate"
    DECISION_DATE = "decisionDate"

    # Decision search
    DECISION_TYPE = "decisionTypeCodeDescriptionText"
    PETITION_TYPE = "decisionPetitionTypeCodeDescriptionText"

    # Status search
    PROSECUTION_STATUS = "prosecutionStatusCodeDescriptionText"
    BUSINESS_ENTITY = "businessEntityStatusCategory"

    # Legal search
    RULE = "ruleBag"  # Search for CFR rules
    STATUTE = "statuteBag"  # Search for statutes

    # Metadata search
    INVENTION_TITLE = "inventionTitle"


# === RED FLAG RULES FOR PETITION QUALITY ASSESSMENT ===
class PetitionRedFlags:
    """
    The CFR rules that classify a petition, plus the three decision outcomes.

    The RULE_* constants are the classification axis: with
    decisionPetitionTypeCodeDescriptionText they say what relief was requested.
    The DECISION_* constants say only whether it was granted. A DENIED decision
    is the ordinary outcome in this corpus and carries no quality signal on its
    own - whole classes (make-special and PPH requests under 37 CFR 1.102(a))
    are refused as a matter of routine - so never derive a red flag from an
    outcome alone. Use these constants when analyzing petition patterns.
    """
    # Revival petitions (application was abandoned)
    RULE_REVIVAL = "37 CFR 1.137"

    # Petitions for supervisory review (examiner disputes)
    RULE_SUPERVISORY_REVIEW = "37 CFR 1.181"

    # Petitions for reconsideration (restriction issues)
    RULE_RECONSIDERATION = "37 CFR 1.182"

    # Special petitions
    RULE_SPECIAL_PETITION = "37 CFR 1.183"

    # Decision outcomes. All three are LIVE in the public corpus, verified
    # 2026-08-30: decisions are overwhelmingly DENIED, while GRANTED and
    # DISMISSED are rare but real (single and low double digits respectively
    # on that date). Do not treat a small result set for GRANTED or DISMISSED
    # as a broken filter, and do not write a count here - the corpus grows.
    DECISION_DENIED = "DENIED"
    DECISION_GRANTED = "GRANTED"
    DECISION_DISMISSED = "DISMISSED"
