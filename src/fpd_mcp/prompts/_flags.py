"""Normalize a prompt template's boolean option to the literal 'true'/'false'.

R-2 (readability-and-naming): every prompt entry point declares its boolean
options as `str` defaulting to `"true"`, interpolates the caller's value into
the emitted template, and the template compares it exactly
(`if "{comparison_analysis}" == "true":`). MCP prompt arguments arrive as
JSON, so a bool is the natural encoding, and a caller passing `True`,
`"True"`, `"TRUE"`, `"yes"` or `"1"` rendered as `if "True" == "true":` —
the whole optional section silently dropped, with no error and no warning.

Normalizing at the entry point makes the emitted comparison correct by
construction; no interpolation site changes.
"""

_TRUE = {"true", "1", "yes", "y", "on"}
_FALSE = {"false", "0", "no", "n", "off"}


def flag(value, *, default: bool = True) -> str:
    """Return the literal 'true' or 'false' for any encoding a caller sends.

    An unrecognized non-empty value falls back to `default` rather than
    silently reading as false, so a typo does not quietly remove a section.
    """
    if value is None or value == "":
        return "true" if default else "false"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip().lower()
    if text in _TRUE:
        return "true"
    if text in _FALSE:
        return "false"
    return "true" if default else "false"
