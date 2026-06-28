"""Tests de la persistance des comptes administrateurs (`nfogen/accounts.py`)."""
from __future__ import annotations

import pytest

from nfogen import accounts


@pytest.fixture(autouse=True)
def _accounts_file(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_ACCOUNTS_FILE", str(tmp_path / "accounts.json"))


def test_not_configured_without_env_var(monkeypatch):
    monkeypatch.delenv("NFOGEN_ACCOUNTS_FILE", raising=False)
    assert accounts.is_configured() is False
    assert accounts.authenticate("admin", "x") is False
    with pytest.raises(accounts.AccountsError):
        accounts.list_accounts()


def test_create_then_authenticate():
    accounts.create_account("admin1", "secret123")
    assert accounts.authenticate("admin1", "secret123") is True
    assert accounts.authenticate("admin1", "mauvais") is False
    assert accounts.authenticate("inconnu", "secret123") is False


def test_password_never_stored_in_clear(tmp_path):
    accounts.create_account("admin1", "secret123")
    raw = (tmp_path / "accounts.json").read_text(encoding="utf-8")
    assert "secret123" not in raw
    assert "pbkdf2_sha256$" in raw


def test_list_accounts_never_exposes_hash():
    accounts.create_account("admin1", "secret123")
    accounts.create_account("admin2", "autresecret")
    assert accounts.list_accounts() == ["admin1", "admin2"]


def test_create_rejects_duplicate_username():
    accounts.create_account("admin1", "secret123")
    with pytest.raises(accounts.AccountsError):
        accounts.create_account("admin1", "autre")


def test_create_rejects_invalid_username():
    with pytest.raises(accounts.AccountsError):
        accounts.create_account("../escape", "secret123")


def test_create_rejects_empty_password():
    with pytest.raises(accounts.AccountsError):
        accounts.create_account("admin1", "")


def test_delete_removes_account():
    accounts.create_account("admin1", "secret123")
    accounts.create_account("admin2", "autresecret")
    accounts.delete_account("admin1")
    assert accounts.list_accounts() == ["admin2"]
    assert accounts.authenticate("admin1", "secret123") is False


def test_delete_unknown_account_raises():
    accounts.create_account("admin1", "secret123")
    with pytest.raises(accounts.AccountsError):
        accounts.delete_account("inconnu")


def test_delete_last_account_refused():
    accounts.create_account("admin1", "secret123")
    with pytest.raises(accounts.AccountsError):
        accounts.delete_account("admin1")
    assert accounts.list_accounts() == ["admin1"]  # toujours present


def test_verify_password_rejects_malformed_hash():
    assert accounts.verify_password("x", "pas-un-hash-valide") is False
    assert accounts.verify_password("x", "") is False
