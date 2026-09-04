"""The one statement of how a petition decision may and may not be read.

Every prompt template interpolates DECISION_NOTE near the top of its emitted
text, so the rule is stated once and cannot drift between ten templates.

Why it exists: the templates were written around an assumption that a DENIED
petition is evidence of a defect (weak arguments, procedural errors, poor
prosecution). It is not. The public corpus is overwhelmingly DENIED, and whole
petition classes are refused as a matter of routine - a make-special or PPH
request under 37 CFR 1.102(a) is refused as a scheduling decision, and those
refusals dominate the denials. The classification axis is
decisionPetitionTypeCodeDescriptionText plus ruleBag, which say what relief was
requested; the decision value says only whether it was granted. The same
correction was applied to the tools' llm_guidance and to
FPD_get_guidance(section='red_flags'); this module keeps the prompt surface
consistent with both.

The text is deliberately parameter-free: it interpolates into an f-string
template as {DECISION_NOTE} and carries no braces of its own.
"""

DECISION_NOTE = """\
## HOW TO READ A PETITION DECISION (applies to every phase below)

Classify each petition on `decisionPetitionTypeCodeDescriptionText` and
`ruleBag` - what relief was REQUESTED - before reading
`decisionTypeCodeDescriptionText`, which says only whether it was granted.

- DENIED is the ordinary outcome in this corpus. Whole classes are refused
  routinely: a petition to make special or a PPH request under 37 CFR 1.102(a)
  is refused as a scheduling decision, not as a finding about the application,
  the portfolio or the practitioner.
  A denial carries NO quality signal on its own.
- Compare an outcome only against other petitions of the SAME type. A denial
  rate computed across mixed petition types measures the mix, not quality, so
  do not report one for a company, an examiner or an art unit.
- The signal, when there is one, is the RULE the petition was filed under: a
  37 CFR 1.137 revival says the application went abandoned; a 37 CFR 1.181
  supervisory-review petition says there was a dispute with the examiner. Those
  are facts about what happened, and they hold whichever way the petition was
  decided.
- There is no published threshold at which a petition rate or a denial rate
  marks anyone as an outlier. Compute a baseline over comparable subjects in
  the same session and report against it, or report the raw counts and say no
  baseline was established. Never state a band you did not measure.
- Read the decision document before characterizing any denial.
"""
