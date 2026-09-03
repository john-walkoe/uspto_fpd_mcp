"""Constant-time credential comparison that cannot raise.

L-1 (auth AUTH-4): `secrets.compare_digest` requires both operands to be
ASCII-only when they are `str`. A header carrying a non-ASCII byte therefore
raised `TypeError` INSIDE the auth check, which the surrounding handler did
not catch, so a malformed credential produced HTTP 500 instead of 401 at five
sites. A 500 on a bad credential is both a worse answer and a cheap oracle.

Non-ASCII is rejected up front: no credential this server issues contains
one, so the comparison is not worth attempting.
"""

import hmac
from typing import Optional


def compare_credential(supplied: Optional[str], expected: Optional[str]) -> bool:
    """True when `supplied` equals `expected` in constant time.

    Returns False (never raises) for a missing, empty or non-ASCII value.
    """
    if not supplied or not expected:
        return False
    if not isinstance(supplied, str) or not isinstance(expected, str):
        return False
    if not supplied.isascii() or not expected.isascii():
        return False
    return hmac.compare_digest(supplied, expected)
