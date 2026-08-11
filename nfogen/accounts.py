"""Comptes administrateurs nommes (`NFOGEN_ACCOUNTS_FILE`), alternative a
l'unique `NFOGEN_API_TOKEN` partage.

Un seul role existe ("administrateur") : un compte nomme donne acces exactement
aux memes routes que le token. L'interet n'est pas une granularite de droits,
mais de pouvoir distinguer/revoquer un acces individuel sans toucher au
secret des autres.

Fichier JSON `{"identifiant": "<hash>", ...}` -- jamais les mots de passe en
clair (PBKDF2-HMAC-SHA256). Relu a chaque authentification (pas de cache).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ALGO = "pbkdf2_sha256"
_ITERATIONS = 260_000


class AccountsError(ValueError):
    """Erreur utilisateur (entree invalide) : a traduire en HTTP 400 cote API."""


def is_configured() -> bool:
    return bool(os.environ.get("NFOGEN_ACCOUNTS_FILE"))


def _path() -> Path:
    root = os.environ.get("NFOGEN_ACCOUNTS_FILE")
    if not root:
        raise AccountsError(
            "NFOGEN_ACCOUNTS_FILE n'est pas configuree : aucun compte administrateur ne peut etre gere."
        )
    return Path(root)


def _check_username(username: str) -> None:
    if not _USERNAME_RE.match(username or ""):
        raise AccountsError(
            f"Identifiant invalide : '{username}' (lettres/chiffres/'-'/'_' uniquement)."
        )


def hash_password(password: str) -> str:
    """`pbkdf2_sha256$<iterations>$<sel hex>$<hash hex>` -- sel aleatoire par mot de passe."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS)
    return f"{_ALGO}${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Comparaison en temps constant (`hmac.compare_digest`)."""
    try:
        algo, iterations_s, salt, expected_hex = hashed.split("$")
        if algo != _ALGO:
            return False
        iterations = int(iterations_s)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return hmac.compare_digest(digest.hex(), expected_hex)


def _load() -> dict[str, str]:
    path = _path()
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(accounts: dict[str, str]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(accounts, indent=2, ensure_ascii=False), encoding="utf-8")


def list_accounts() -> list[str]:
    """Identifiants existants, jamais les hachages."""
    return sorted(_load())


def create_account(username: str, password: str) -> None:
    _check_username(username)
    if not password:
        raise AccountsError("Le mot de passe ne peut pas etre vide.")
    accounts = _load()
    if username in accounts:
        raise AccountsError(f"Le compte '{username}' existe deja.")
    accounts[username] = hash_password(password)
    _save(accounts)


def delete_account(username: str) -> None:
    """Refuse de supprimer le dernier compte restant (verrouillage hors gestion)."""
    accounts = _load()
    if username not in accounts:
        raise AccountsError(f"Compte inconnu : '{username}'.")
    if len(accounts) <= 1:
        raise AccountsError(
            "Impossible de supprimer le dernier compte administrateur restant."
        )
    del accounts[username]
    _save(accounts)


def authenticate(username: str, password: str) -> bool:
    if not is_configured():
        return False
    try:
        accounts = _load()
    except (json.JSONDecodeError, OSError):
        return False
    hashed = accounts.get(username)
    if hashed is None:
        return False
    return verify_password(password, hashed)
