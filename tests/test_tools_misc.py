"""Tool-level tests for FPD_get_guidance and FPD_manage_users.

fpd_manage_users doesn't go through mock_runtime (it talks to the mcp_users
store, not the FPD API client) — _get_user_store() is patched directly with
an in-memory fake so tests never touch a real sqlite file.
"""

from datetime import datetime, timezone

import pytest

import fpd_mcp.tools.admin as admin_module
from fpd_mcp.tools.admin import fpd_manage_users
from fpd_mcp.tools.guidance import fpd_get_guidance


class _FakeUserStore:
    def __init__(self):
        self._users = {}

    async def upsert_user(self, email, role="user", display_name=None, notes=None, active=True):
        existing = self._users.get(email, {})
        self._users[email] = {
            "email": email,
            "display_name": display_name if display_name is not None else existing.get("display_name"),
            "role": role,
            "active": active,
            "added_at": existing.get("added_at", datetime.now(timezone.utc)),
            "last_login_at": existing.get("last_login_at"),
            "last_login_idp": existing.get("last_login_idp"),
            "notes": notes if notes is not None else existing.get("notes"),
        }

    async def get_user(self, email):
        return self._users.get(email)

    async def set_active(self, email, active):
        if email not in self._users:
            return False
        self._users[email]["active"] = active
        return True

    async def list_users(self):
        return list(self._users.values())


@pytest.fixture
def fake_user_store(monkeypatch):
    store = _FakeUserStore()
    monkeypatch.setattr(admin_module, "_get_user_store", lambda: store)
    return store


async def test_get_guidance_overview_returns_string():
    result = await fpd_get_guidance()

    assert isinstance(result, str)
    assert "overview" in result.lower() or "sections" in result.lower()


async def test_get_guidance_unknown_section():
    result = await fpd_get_guidance(section="not_a_real_section")

    assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# red_flags section framing (QA ledger 2026-09-03, tester report B7 finding F1)
# ---------------------------------------------------------------------------

async def test_red_flags_section_does_not_make_denial_a_red_flag():
    """DENIED is the ordinary outcome in this corpus; the section must classify
    on decisionPetitionTypeCodeDescriptionText + ruleBag instead."""
    result = await fpd_get_guidance(section="red_flags")

    lowered = result.lower()
    assert "unsuccessful arguments or procedural errors" not in lowered
    assert "red flag severity:** high - indicates documented procedural problems" not in lowered
    assert "decisionPetitionTypeCodeDescriptionText" in result
    assert "no quality signal on its own" in lowered


async def test_red_flags_section_serves_no_petition_rate_threshold():
    """The old 'above 15 percent' art unit trigger had no measured basis; the
    replacement asks for a baseline computed in the same session."""
    result = await fpd_get_guidance(section="red_flags")

    assert ">15%" not in result
    # No numeric trigger is served as an indicator any more; the only surviving
    # mention of 15 percent is the sentence explaining why it was removed.
    assert "**Indicator:** Art unit petition rate" not in result
    assert "no fixed threshold" in result.lower()
    assert "same session" in result.lower()


async def test_manage_users_list_empty(fake_user_store):
    result = await fpd_manage_users(action="list")

    assert result["action"] == "list"
    assert result["users"] == []


async def test_manage_users_add_then_list(fake_user_store):
    add_result = await fpd_manage_users(
        action="add", email="alice@example.com", role="user", display_name="Alice"
    )

    assert add_result["action"] == "add"
    assert len(add_result["users"]) == 1
    assert add_result["users"][0]["email"] == "alice@example.com"
    assert add_result["users"][0]["role"] == "user"


async def test_manage_users_rejects_invalid_email(fake_user_store):
    result = await fpd_manage_users(action="add", email="not-an-email", role="user")

    assert "error" in result
    assert "invalid email" in result["error"].lower()


async def test_manage_users_rejects_invalid_action(fake_user_store):
    result = await fpd_manage_users(action="delete_everything")

    assert "error" in result


async def test_manage_users_set_role_no_such_user(fake_user_store):
    result = await fpd_manage_users(action="set_role", email="ghost@example.com", role="admin")

    assert "error" in result
    assert "no such user" in result["error"].lower()


async def test_red_flags_section_lists_the_live_revival_type_codes():
    """562 and 529 are live on 37 CFR 1.137 records; the served list must say
    it is observed rather than published."""
    result = await fpd_get_guidance(section="red_flags")

    assert "562" in result
    assert "529" in result
    assert "To Withdraw A Holding of Abandonment in Pre-Exam Status" in result
    assert "observed, not exhaustive" in result.lower()


async def test_coverage_section_states_a_completeness_floor_not_a_cutoff():
    """Decisions from 2011, 2014 and 2015 are live in art unit 2128 alone, so
    2022 marks where coverage becomes systematic, not where data begins."""
    result = await fpd_get_guidance(section="coverage")

    assert "completeness floor, not a cutoff" in result.lower()
    assert "2011" in result
    assert "inconclusive" in result.lower()
    # The superseded instruction was "report that the decision predates the
    # dataset"; it is now explicitly ruled out rather than taught.
    assert "do not report that the decision predates" in result.lower()


async def test_coverage_section_documents_firstapplicantname_sparsity():
    """Field-level coverage is a third gap alongside the filing floor and the
    decisions floor, and an absent field is not a wrong field name."""
    result = await fpd_get_guidance(section="coverage")

    assert "firstApplicantName is sparse" in result
    assert "47 of 53" in result
    assert "98 of 100" in result
    assert "Absent, null and empty are the same case" in result
