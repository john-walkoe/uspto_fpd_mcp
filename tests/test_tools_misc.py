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
