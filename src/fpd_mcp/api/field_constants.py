"""
USPTO Final Petition Decisions API Field Constants

This module defines all USPTO FPD API field names as constants to eliminate
magic strings throughout the codebase and provide a single source of truth.

Based on USPTO Open Data Portal API - Final Petition Decisions endpoint.
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
    BUSINESS_ENTITY_STATUS_CATEGORY = "businessEntityStatusCategory"  # Small/Undiscounted

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
    Common petition types and rules that indicate potential quality issues.

    Use these constants when analyzing petition patterns for red flags.
    """
    # Revival petitions (application was abandoned)
    RULE_REVIVAL = "37 CFR 1.137"

    # Petitions for supervisory review (examiner disputes)
    RULE_SUPERVISORY_REVIEW = "37 CFR 1.181"

    # Petitions for reconsideration (restriction issues)
    RULE_RECONSIDERATION = "37 CFR 1.182"

    # Special petitions
    RULE_SPECIAL_PETITION = "37 CFR 1.183"

    # Decision outcomes
    DECISION_DENIED = "DENIED"
    DECISION_GRANTED = "GRANTED"
    DECISION_DISMISSED = "DISMISSED"
