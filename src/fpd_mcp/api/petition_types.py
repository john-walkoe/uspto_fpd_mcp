"""Petition type vocabulary: `decisionPetitionTypeCode` -> USPTO's own name.

USPTO publishes no enumeration of petition type codes (neither the ODP
swagger nor petition-decision-schema.json lists them; the schema still types
the field as an integer). This table was derived on 2026-10-06 from the live
endpoint, one code at a time, and every name is USPTO's
`decisionPetitionTypeCodeDescriptionText` VERBATIM, typos and mixed case
included ("ISUE", "ADDIITONAL", "WITHDRAWAL A HOLDING"). Do not correct them:
a name here is quoted data, and a caller may paste it into a query.

How each pairing was established (docs/PETITION-STATISTICS.md, section
"Petition type table"):

- 133 codes: a facet on `decisionPetitionTypeCode` and a facet on
  `decisionPetitionTypeCodeDescriptionText` over the whole corpus, paired
  where a count was unique on both sides.
- 10 codes whose count matched no single name (several codes share a name,
  e.g. 547 and 549 are both "PTA Recalculation"): one facet call per code,
  `q=decisionPetitionTypeCode:<code>`, which returned exactly one name each.
- 48 low-count codes (274 records in all): every record fetched, each code
  carrying exactly one name.

Cross-check: for every name, the sum of its codes' counts equals that name's
own facet count, over all 191 codes and 184 names (1,113,547 records on
2026-10-06). The table holds names only; counts are fetched live by
FPD_list_petition_types, because the corpus moves (it shrank by 103 records
between 2026-10-05 and 2026-10-06).

A code the live facet returns that is not below is reported as unnamed, never
guessed.
"""

import re
from typing import Dict, List, Optional, Tuple

#: Date this table was derived from the live endpoint.
PETITION_TYPE_TABLE_AS_OF = "2026-10-06"

PETITION_TYPE_NAMES: Dict[int, str] = {
    201: "TO REVIEW A REFUSAL TO GRANT A REQUEST FOR CERTIFICATE OF CORRECTION (E.G., 37 CFR 1.322 AND 1.323)",
    202: "TO PERMIT CONCURRENT INTER PARTES AND EX PARTES PROSECUTION (E.G., 37 CFR 1.212)",
    203: "TO INVOKE SUPERVISORY AUTHORITY OF THE COMMISSIONER IN MATTERS CONCERNING THE OFFICE OF ADMINISTRATION NOT PROVIDED FOR IN OTHER CODES (E.G., 37 CFR 1.183)",
    205: "TO PERMIT WITHDRAWAL OF AN ATTORNEY OR AGENT (E.G., 35 CFR 1.36)",
    206: "TO EXPUNGE PAPER(S) FROM AN APPLICATION",
    210: "REQUEST FOR RECONSIDERATION OF PETITION DECISION",
    221: "TO CHANGE THE FILING DATE IN A HAGUE APPLICATION",
    222: "TO CONVERT A HAGUE APPLICATION TO A REGULAR DESIGN APPLICATION",
    223: "TO MAKE SPECIAL FOR SEARCH COLLOABORATION WITH JPO",
    224: "TO MAKE SPECIAL FOR SEARCH COLLOABORATION WITH KIPO",
    225: "TO MAKE SPECIAL FOR SEARCH COLLABORATION PILOT (CSP 2.0)",
    250: "RELATING TO INTERNATIONAL APPLICATIONS",
    251: "RELATING TO THE INTERNATIONAL FILING DATE",
    252: "RELATING TO LACK OF APPLICANT(S) SIGNATURE",
    253: "RELATING TO THE DRAWINGS",
    254: "RELATING TO CHANGE IN DESIGNATION",
    255: "RELATING TO THE PRIORITY CLAIM",
    256: "RELATING TO DEFECTIVE TRANSLATION OF PCT AMENDMENT OR ANNEX",
    257: "RELATING TO APPLICANT'S QUALIFICATION AS A US RESIDENT OR NATIONAL",
    258: "TO WAIVE THE RULES (37 CFR 1.183)",
    259: "RELATING TO REFUND AND FEE PROBLEMS",
    260: "RELATING TO AMENDMENTS",
    261: "RELATING TO EXPRESS MAIL/CERTIFICATE OF MAILING",
    262: "TO INVOKE SUPERVISORY AUTHORITY (37 CFR 1.181)",
    263: "TO CONVERT FILING FROM 35 USC 111 TO 35 USC 371",
    264: "TO CONVERT FILING FROM 35 USC 371 TO 35 USC 111",
    265: "RELATING TO CHAPTER II/DEMAND",
    266: "TO WITHDRAW AN INTERNATIONAL APPLICATION",
    270: "RELATING TO NATIONAL STAGE APPLICATION",
    271: "TO REVIVE AN ABANDONED INTERNATIONAL APPLICATION - UNAVOIDABLE DELAY  - 37 CFR 1.137(A)",
    272: "TO REVIVE AN ABANDONED INTERNATIONAL APPLICATION - UNINTENTIONAL DELAY, NO ADDITIONAL INFORMATION REQUIRED (37 CFR 1.137(A))",
    273: "TO WITHDRAWAL A HOLDING OF ABANDONMENT - 37 CFR 1.181",
    274: "TO INVOKE SUPERVISORY AUTHORITY IN NATIONAL STAGE - 37 CFR 1.181",
    275: "TO WAIVE/SUSPEND RULES IN NATIONAL STAGE -  37 CFR 1.183",
    276: "TO DECIDE MATTERS BEFORE THE A/C FOR PATENTS IN NATIONAL STAGE - 37 CFR 1.182",
    277: "TO DECIDE MATTERS REGARDING INVENTORSHIP IN NATIONAL STAGE - 37 CFR 1.497(D)",
    278: "TO DECIDE MATTERS REGARDING REFUSAL TO SIGN IN NATIONAL STAGE - 37 CFR 1.47",
    279: "TO DECIDE MATTERS WHERE THE INVENTOR IS DECEASED 37 CFR 1.42",
    280: "TO DECIDE MATTERS REGARDING 102(E)/371 DATE",
    281: "TO DECIDE MATTERS REGARDING EXPRESS MAIL IN NATIONAL STAGE - 37 CFR 1.10",
    282: "TO DECIDE MATTERS REGARDING ACCESS TO NATIONAL STAGE APPLICATIONS -37 CFR 1.14",
    283: "UNINTENTIONAL DELAY CLAIMING BENEFIT/PRIORITY, NO ADDIITONAL INFORMATION REQUIRED; DELAY IN FILING CERTIFIED COPY; RESTORATION OF PRIORITY (37 CFR 1.55 OR 1.78)",
    284: "To decide matters before the A.C for patents in International Stage\t (37 CFR 1.182)",
    289: "Petition to make special (New Route)",
    292: "TO REVIVE AN ABANDONED INTERNATIONAL APPLICATION - UNINTENTIONAL DELAY, ADDITIONAL INFORMATION REQUIRED  (37 CFR 1.137(A))",
    293: "UNINTENTIONAL DELAY CLAIMING BENEFIT/PRIORITY, ADDITIONAL INFORMATION REQUIRED (37 CFR 1.55 OR 1.78)",
    297: "REQUEST FOR CORRECTED PATENT APPLICATION PUBLICATION.",
    298: "WITHDRAWAL OF POWER OF ATTORNEY",
    299: "FOR OTHER MATTERS BEFORE THE INTERNATIONAL DIVISION",
    301: "RELATING TO PUBLIC USE PROCEEDINGS (37 CFR 1.292)",
    302: "TO MAKE APPLICATION SPECIAL-PROSPECTIVE MANUFACTURE (37 CFR 1.102, MPEP 708.02",
    303: "TO MAKE SPECIAL INFRINGEMENT (37 CFR 1.102, MPEP 708.02)",
    305: "TO WAIVE OR SUSPEND RULES (37 CFR 1.183)",
    306: "EXPUNGE A PAPER FROM AN APPLICATION FILE (37 CFR 1.59) OR AN ASSIGNMENT RECORD (37 CFR 1.182)",
    307: "WITHDRAW AS ATTORNEY OR AGENT (37 CFR 1.36)",
    308: "FOR ACCESS TO APPLICATION EXCEPT RE-PROCEEDINGS BEFORE PTAB (37 CFR 1.14; MPEP 103,104)",
    310: "RELATING TO RE-EXAMINATION (37 CFR 1.181-1.183)",
    311: "FOR CORRECTION OF INVENTORSHIP FOR APPLICATIONS NO FILING",
    312: "FOR CORRECTION OF INVENTORSHIP RE PCT APPLICATIONS (37 CFR 1.47)",
    313: "FOR FILING APPLICATION WITHOUT ONE OR MORE INVENTORS (37 CFR 1.46)",
    315: "FOR EXTENTION OF TIME WITHOUT FEE IN APPLICATION (37 CFR 1.136(B))",
    320: "MAKE ENTITY STATUS SMALL",
    321: "MAKE ENTITY STATUS LARGE",
    322: "Workflow Petition to make special",
    399: "FOR MATTERS BEFORE A/C FOR PATENTS - NOT SPECIFIED",
    401: "FOR FILING DATE (MPEP 506)",
    408: "Rule 53 - Lost Application,  Postcard Receipt, method claims, incorporation by reference, misnumbered and mislabeled drawings, conversions, lost applications",
    410: "RELATING TO A FILING DATE UNDER 37 CFR 1.62",
    411: "FILING DATE FOR APPLICATION FILED BY EXPRESS MAIL (37 CFR 1.10)",
    412: "FOR FILING DATE (37 CFR 1.53)",
    414: "RELATING TO CONVERSION OF UTILITY TO PROVISIONAL APPLICATION",
    416: "FOR FILING DATE OF CORRESPONDENCE SENT BY PRIORITY MAIL EXPRESS (37 CFR 1.10)",
    417: "Petition under 37 CFR 1.57(a) to accord a filing date for incorporation of omitted items",
    420: "Foreign Filing License Request",
    421: "REQUEST FOR RETROACTIVE FOREIGN FILING LICENSE",
    499: "FOR MATTERS BEFORE A/C FOR PATENTS - NOT SPECIFIED",
    501: "TO REVIVE AN ABANDONED APPLICATION - UNAVOIDABLE DELAY (37 CFR 1.137(A))",
    502: "REVIVE AN APPLICATION ABANDONED BY OPAP OR THE TC - UNINTENTIONALLY DELAYED REPLY, NO ADDITIONAL INFORMATION REQUIRED (37 CFR 1.137(A))",
    503: "FOR SUSPENSION OR WAIVER OF A RULE (37 CFR 1.183)",
    504: "TO INVOKE SUPERVISORY AUTHORITY RE - PATENT EXAMINING",
    505: "To withdraw from issue after payment of the issue fee \t(37 CFR 1.313(c)(1) or (2).",
    506: "WITHDRAW FROM ISSUE AFTER PAYMENT OF ISSUE FEE (37 CFR 1.313(C)(3))",
    507: "DELAYED SUBMISSION OF CERTIFIED COPY OF FOREIGN APPLICATION (37 CFR 1.55)",
    508: "TO DEFER ISSUANCE OF PATENT (37 CFR 1.314)",
    509: "TO ACCEPT LATE PAYMENT OF ISSUE FEE - UNAVOIDABLE DELAY (37 CFR 1.155(B) OR 37 CFR 1.316(B))",
    510: "REVIVE AN APPLICATION ABANDONED BY ODM - UNINTENTIONALLY DELAYED REPLY, NO ADDITIONAL INFORMATION REQUIRED (37 CFR 1.137(A))",
    512: "TO ACCEPT LATE PAYMENT OF BALANCE OF ISSUE FEE - UNINTENTIONAL LATE PAYMENT (37 CFR 1.317(C))",
    515: "TO INVOKE SUPERVISORY AUTHORITY - RE NON-PATENT EXAMINING (37 CFR 1.181)",
    516: "TO WAIVE/SUSPEND RULES RE NON-PATENT EXAMINING MATTERS (37 CFR 1.183)",
    517: "1.182 DESIGN TO UTILITY / UTILITY TO DESIGN CONVERSIONS.",
    518: "37 CFR 1.182 request for expedited consideration of matter before the DCPEP",
    519: "Rule 182 - INVENTOR NAME CHANGE, ORDER OF INVENTOR, ATTY/ASSIGNEE NAME CHANGE, DUPLICATE OMITTED ITEMS LETTERS PATENT, REPLY TO NOTICE OF OMITTED ITDUPLICATE PATENT AND/OR REPRINT LETTERS PATENTEMS W/POSTCARD RECEIPT,",
    520: "Rule 182 - Matters Not Provided for by Code 519",
    521: "TO REVIEW REFUSAL TO ACCEPT AND RECORD MAINTENANCE FEE APPLICATION FILED ON OR AFTER 8/27/82 (37 CFR 1.377",
    523: "CORRECT ASSIGNEE INFORMATION IN PATENT (37 CFR 3.81)",
    525: "TO WITHDRAW A HOLDING OF ABANDONMENT",
    529: "To Withdraw A Holding of Abandonment in Pre-Exam Status",
    532: "TO ACCEPT UNAVOIDABLY DELAYED PAYMENT OF MAINTENANCE FEE (37 CFR 1.378(C))",
    533: "REINSTATE PATENT - UNINTENTIONALLY DELAYED PAYMENT OF MAINTENANCE FEE, NO ADDITIONAL INFORMATION REQUIRED (37 CFR 1.378(A))",
    534: "PETITIONS RELATED TO REEXAMINATION PROCEEDINGS",
    535: "LATE BENEFIT/PRIORITY CLAIM - UNINTENTIONALLY DELAYED BENEFIT/PRIORITY CLAIM, NO ADDITIONAL INFORMATION REQUIRED (37 CFR 1.55 OR 1.78)",
    536: "REVIVE AN APPLICATION UNDER 37 CFR 1.137(F), NO ADDITIONAL INFORMATION REQUIRED",
    538: "Correction of Data on 85b or Printed Patent - Rule 183",
    540: "RESTORATION OF PRIORITY UNDER 37 CFR 1.55(c) OR 1.78(b)",
    547: "PTA Recalculation",
    548: "Petition for OPLA",
    549: "PTA Recalculation",
    550: "CORRECTION OF PATENT TERM ADJUSTMENT VALUE AFTER ALLOWANCE AND BEFORE ISSUE",
    551: "CORRECTION OF PATENT TERM ADJUSTMENT VALUE AFTER ISUE",
    552: "Rule 705c - Reinstatement of Reduced Term",
    553: "Petition filed for PTE, rule 701",
    554: "PTA RECALCULATIONS FOR IDS SUBMISSIONS WITH SAFE HARBOR STATEMENT",
    555: "To withdraw from issue after payment of issue fee (37 CFR 1.313(c)(1) or (2)) with assigned patent number.",
    556: "PETITION TO WITHDRAW FROM ISSUE GRANTED UNDER 37 CFR 1.313(c)(3) WITH ASSIGNED PATENT NUMBER .  APPLICATION IS ABANDONED.",
    560: "REVIVE AN APPLICATION ABANDONED BY ODM - UNINTENTIONALLY DELAYED REPLY, ADDITIONAL INFORMATION REQUIRED (37 CFR 1.137(A))",
    561: "REVIVE AN APPLICATION FOR CONTINUITY PURPOSES ONLY, NO ADDITIONAL INFORMATION REQUIRED (37 CFR 1.137(A))",
    562: "REVIVE AN APPLICATION ABANDONED BY OPAP OR THE TC - UNINTENTIONALLY DELAYED REPLY, ADDITIONAL INFORMATION REQUIRED (37 CFR 1.137(A))",
    563: "REINSTATE PATENT - UNINTENTIONALLY DELAYED PAYMENT OF MAINTENANCE FEE, ADDITIONAL INFORMATION REQUIRED (37 CFR 1.378(A))",
    565: "LATE BENEFIT/PRIORITY CLAIM - UNINTENTIONALLY DELAYED BENEFIT/PRIORITY CLAIM, ADDITIONAL INFORMATION REQUIRED (37 CFR 1.55 OR 1.78)",
    566: "REVIVE AN APPLICATION UNDER 37 CFR 1.137(F), ADDITIONAL INFORMATION REQUIRED",
    571: "REVIVE AN APPLICATION FOR CONTINUITY PURPOSES ONLY, ADDITIONAL INFORMATION REQUIRED (37 CFR 1.137(A))",
    577: "Response to Combined Notice and Order 35 USC 41(j) or 123(f), assertion or certification was not falsely made.",
    578: "Response to combined notice and order (35 USC 41(j) or 123(f), false assertion or certification with explanation of good faith",
    579: "Response to combined notice and order (35 USC 41(j) or 123(f), false assertion or certification with payment of fine assessed.",
    580: "Miscellaneous",
    581: "Miscellaneous",
    582: "Miscellaneous",
    597: "CERTIFICATION AND REQUEST FOR DISASTER RELIEF",
    598: "Miscellaneous type E",
    599: "Miscellaneous Outgoing Correspondence, PTE Correction Letter, Request for Information (All Rules), Notification of Misapplied Maint. Fee (1.377)",
    600: "MISCELLANEOUS OUTGOING CORRECTED DECISION",
    601: "TO MAKE APPLICATION SPECIAL ON GROUND OF AGE (37 CFR 1.102, MPEP 708.02)",
    602: "TO MAKE SPECIAL CONTINUITY OF EARLIER APPLICATION (37 CFR 1.102, MPEP 708.02)",
    603: "TO MAKE SPECIAL ENVIRONMENT QUALITY PROGRAM (37 CFR 1.102, MPEP 708.02)",
    604: "TO MAKE SPECIAL ACCELERATED EXAMINATION (37 CFR 1.102, MPEP 708.02",
    605: "TO MAKE SPECIAL ENERGY PROGRAM (37 CFR 1.102, MPEP 708.02)",
    606: "TO MAKE SPECIAL RECOMBINANT DNA (37 CFR 1.102, MPEP 708.02)",
    607: "REASONS NOT PROVIDED FOR IN CODES 601-606",
    608: "TO REOPEN PROSECUTION AFTER BOARD DECISION (37 CFR 1.198)",
    609: "FOR REVIEW OF FINAL RESTRICTION REQUIREMENT (37 CFR 1.144)",
    610: "INVOKING AUTHORITY OF COMMISSIONER UNDER 37 CFR 1.181 NOT SPECIFIED IN CODES 611-617",
    611: "RELATING TO THE PREMATURENESS OF FINAL REJECTION (37 CFR 1.181, MPEP 706.07)",
    612: "RELATING TO THE REFUSAL TO ENTER AN AMENDMENT (37 CFR 1.181 AND 1.127, MPEP 714.19)",
    613: "TO WITHDRAW A HOLDING OF ABANDONMENT (37 CFR 1.137, MPEP 711.03)",
    614: "TO WITHDRAW A HOLDING OF ABANDONMENT (37 CFR 1.181 AND 1.127, MPEP 714.19)",
    615: "RELATING TO FORMAL SUFFICIENCY/PROPRIETY OF AFFIDAVITS (37 CFR 1.131, 1.132, 1.608, MPEP 608.04(C)",
    616: "TO INSTITUTE AN INTERFERENCE (37 CFR 1.606)",
    617: "RELATING TO REFUSAL TO ENTER AN AMENDMENT UNDER 37 CFR 1.312",
    618: "FOR CONCURRENT EX PARTE AND INTER PARTE PROCEEDINGS (37 CFR 1.212)",
    619: "FOR RETURN OF ORIGINAL OATH OF PATENT APPLICATION (MPEP 604.04(A))",
    620: "FOR EXTENSION OF TIME (37 CFR 1.136 9B)",
    622: "CONCERNING APPEAL APPLICATION BEFORE TRANSFER OF JURISDICTION TO BOARD OF APPEALS (MPEP 1206)",
    624: "TO MAKE APPLICATION SPECIAL ON GROUND OF HEALTH (37 CFR 1.102, MPEP 708.02)",
    625: "TO REINSTATE APPEALS DISMISSED IN GROUP",
    626: "FROM DENIAL OF REEXAMINATION REQUEST (37 CFR 515(C)",
    627: "TO ENTER AMENDMENT AFTER PAYMENT OF ISSUE FEE (37 CFR 1.312(B))",
    628: "FROM REFUSAL TO ISSUE A CERTIFICATE OF CORRECTION (37 CFR 1.181, MPEP 1480-1485)",
    629: "FOR WITHDRAWAL OF ATTORNEY FROM APPLICATION PENDING IN GROUP (37 CFR 1.36)",
    630: "FOR EXTENSION OF TIME IN A REEXAMINATION (37 CFR 1.550(C)",
    631: "TO MERGE MULTIPLE REEXAMINATION PROCEEDINGS (37 CFR 1.565(C), MPEP 2283)",
    632: "TO EFFECT A SECOND CORRECTION OF INVENTORSHIP (37 CFR 1.48, MPEP 201.03)",
    633: "SUPERCONDUCTIVITY",
    634: "TO CORRECT INVENTORSHIP IN A PATENT NOT IN INTERFERENCE (37 CFR 1.324, MPEP 1481)",
    635: "TO CHANGE INVENTORSHIP IN AN APPLICATION (37 CFR 1.48)",
    636: "TO CHANGE INVENTORSHIP IN A PATENT (37 CFR 1.324)",
    637: "TO WITHDRAW FROM ISSUE BEFORE PAYMENT OF AN ISSUE FEE (37 CFR 1.313(A))",
    638: "Streamlined Claim Set Pilot",
    639: "TO MAKE SPECIAL PROSPECTIVE MANUFACTURE (37 CFR 1.102, MPEP 708.02)",
    640: "TO MAKE SPECIAL INFRINGEMENT (37 CFR 1.102, MPEP 708.02)",
    641: "Climate Change Mit. Pilot",
    642: "Track One",
    643: "Track One Request",
    644: "PETITION TO MAKE SPECIAL UNDER THE LAW SCHOOL PILOT PROGRAM",
    645: "Climate Change Adaptation Pilot",
    646: "TO MAKE SPECIAL FOR ACCELERATED EXAMINATION",
    647: "First-Time Filer Expedited Examination Pilot",
    648: "Automated Search Pilot Program",
    649: "PPH Special To Regular",
    650: "PETITION FOR EXPRESS ABANDONMENT UNDER 37 CFR 1.138(c)",
    651: "Petition for express abandonment under rule 37 CFR 1.138(d)",
    652: "Petition to make special-PPH",
    653: "TO WITHDRAWAL A HOLDING OF ABANDONMENT - 37 CFR 1.181",
    654: "REQUEST FOR CORRECTED PATENT APPLICATION PUBLICATION.",
    655: "Petition to Make Special-SPA",
    690: "Petition Related to Color Drawings or Photographs for Plants and Designs",
    691: "Petition Related to Color Drawings or Photographs for Utilities",
    697: "EXPUNGE ABEYANCE ONLY",
    698: "EXPUNGE FINAL DECISION NOT HELD IN ABEYANCE",
    699: "FOR MATTERS BEFORE TECHNOLOGY CENTER - NOT SPECIFIED",
    710: "FOR EXTENSION OF TIME TO FILE SUPPLEMENTAL REPLY BRIEF (37 CFR 1.136)",
    714: "TO REINSTATE APPEAL",
}

#: Plain-English words a caller uses that USPTO's names spell differently,
#: each mapped to regular expressions that do match the names (any one
#: matches). Kept short on purpose: a stem covers its inflections, and a
#: whole-word pattern (`\bpta\b`) keeps "PTA" from matching "PTAB".
_EXAMINER_DISPUTE: Tuple[str, ...] = (
    r"re - patent examining",
    r"final restriction",
    r"not specified in codes 611-617",
    r"prematureness of final",
    r"refusal to enter an amendment",
    r"sufficiency/propriety of affidavits",
)

_SEARCH_SYNONYMS: Dict[str, Tuple[str, ...]] = {
    "revival": (r"\breviv",),
    # Petitions against an examiner's action carry no common word in their
    # names: 504 and the technology-center codes 609-612, 615, 617. Not 515
    # (non-examining) and not 613/614 (holdings of abandonment). A claude.ai
    # run used 504 alone for "petitions against examiner actions" (2026-10-07).
    "examiner": _EXAMINER_DISPUTE,
    "dispute": _EXAMINER_DISPUTE,
    "disputes": _EXAMINER_DISPUTE,
    # USPTO's own name for type 315 spells it "EXTENTION"; match both ways.
    "extension": (r"\bextent?s?ion",),
    "extention": (r"\bextent?s?ion",),
    "revive": (r"\breviv",),
    "pta": (r"term adjustment", r"\bpta\b"),
    "prioritized": (r"track one",),
    "reinstatement": (r"\breinstat",),
    "accelerated": (r"\bspecial\b",),
    "abandonment": (r"\babandon",),
}

_WORD_RE = re.compile(r"[a-z0-9.()]+")


def petition_type_name(code: object) -> Optional[str]:
    """USPTO's name for a type code given as 502, '502' or ' 502 ', else None."""
    try:
        return PETITION_TYPE_NAMES.get(int(str(code).strip()))
    except (TypeError, ValueError):
        return None


def _needles(search: str) -> List[Tuple[str, ...]]:
    """One tuple of alternative patterns per word of `search` (a word with no
    synonym is matched as a plain substring)."""
    return [
        _SEARCH_SYNONYMS.get(word, (re.escape(word),))
        for word in _WORD_RE.findall(search.lower())
    ]


def search_petition_types(search: str) -> List[Tuple[int, str]]:
    """(code, name) pairs whose name contains every word of `search`.

    Case-insensitive substring match on USPTO's name, after mapping a few
    plain-English words to the stems the names use (`revival` -> `reviv`,
    `pta` -> `term adjustment` or the word `pta`). A bare code (`"502"`) matches that
    code.
    """
    text = (search or "").strip()
    if not text:
        return sorted(PETITION_TYPE_NAMES.items())
    if text.isdigit():
        name = PETITION_TYPE_NAMES.get(int(text))
        return [(int(text), name)] if name else []
    needles = _needles(text)
    return [
        (code, name)
        for code, name in sorted(PETITION_TYPE_NAMES.items())
        if all(any(re.search(alt, name.lower()) for alt in alts) for alts in needles)
    ]
