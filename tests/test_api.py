"""Tests du service HTTP (`nfogen/api.py`) : auth par token, CORS, limite de
taille d'upload, et separation des erreurs 400 (client) / 500 (serveur).

`nfogen.api` lit ses options (`NFOGEN_API_TOKEN`, `NFOGEN_CORS_ORIGINS`,
`NFOGEN_MAX_UPLOAD_MB`) depuis l'environnement au moment de l'import : les
tests qui changent ces variables doivent recharger le module pour que le
changement soit pris en compte (cf. fixture `reload_api`).
"""
from __future__ import annotations

import importlib
import io
import threading
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from nfogen import api as api_module
from nfogen.radarr_client import RadarrMovieFile
from nfogen.registry import unregister_profile
from nfogen.sonarr_client import SonarrSeasonFile
from nfogen.torznab_client import TorznabRelease


@pytest.fixture
def reload_api(monkeypatch):
    """Recharge `nfogen.api` apres avoir pose les variables d'environnement
    voulues, et renvoie le module recharge (pour construire un TestClient).
    Remet le module dans son etat par defaut apres le test."""

    def _reload(**env: str | None) -> object:
        for key, value in env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        importlib.reload(api_module)
        return api_module

    yield _reload
    importlib.reload(api_module)  # restaure l'etat par defaut (env deja annulee par monkeypatch)


GAME_PAYLOAD = {"category": "game", "data": {"title": "X", "platform": "PC"}}


# --------------------------------------------------------------------------- #
# Authentification par token : /profiles/store* (toujours protegees par
# NFOGEN_API_TOKEN, contrairement a la generation, cf. section suivante)
# --------------------------------------------------------------------------- #
def test_open_by_default_without_token(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post("/generate/json", json=GAME_PAYLOAD)
    assert resp.status_code == 200


def test_blocks_with_wrong_token(reload_api, tmp_path):
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_PROFILES_DIR=str(tmp_path))
    client = TestClient(mod.app)
    resp = client.get("/profiles/store", headers={"Authorization": "Bearer mauvais"})
    assert resp.status_code == 401


def test_allows_with_correct_token(reload_api, tmp_path):
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_PROFILES_DIR=str(tmp_path))
    client = TestClient(mod.app)
    resp = client.get("/profiles/store", headers={"Authorization": "Bearer secret123"})
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# /generate, /generate/json, /propose-name : ouverts par defaut (deux niveaux
# distincts de la gestion des profils ci-dessus), verrouillables explicitement
# --------------------------------------------------------------------------- #
def test_generate_open_by_default_even_with_token_configured(reload_api):
    """NFOGEN_API_TOKEN protege /profiles/store* mais ne verrouille plus la
    generation a lui seul : la gestion de profils (admin) et la generation
    (ouverte a tous via le web) sont deux niveaux distincts."""
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_REQUIRE_AUTH_FOR_GENERATE=None)
    client = TestClient(mod.app)
    resp = client.post("/generate/json", json=GAME_PAYLOAD)
    assert resp.status_code == 200


def test_generate_lockable_via_require_auth_for_generate(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_REQUIRE_AUTH_FOR_GENERATE="1")
    client = TestClient(mod.app)
    assert client.post("/generate/json", json=GAME_PAYLOAD).status_code == 401
    resp = client.post(
        "/generate/json", json=GAME_PAYLOAD, headers={"Authorization": "Bearer secret123"}
    )
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Rate-limiting de /generate* (NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE, audit du
# 2026-08-11) : complementaire de NFOGEN_MAX_UPLOAD_MB (borne la taille d'UNE
# requete, pas leur NOMBRE). Inactif par defaut (variable absente).
# --------------------------------------------------------------------------- #
def test_generate_rate_limit_disabled_by_default(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE=None)
    client = TestClient(mod.app)
    for _ in range(10):
        assert client.post("/generate/json", json=GAME_PAYLOAD).status_code == 200


def test_generate_rate_limit_blocks_after_threshold(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE="2")
    client = TestClient(mod.app)
    assert client.post("/generate/json", json=GAME_PAYLOAD).status_code == 200
    assert client.post("/generate/json", json=GAME_PAYLOAD).status_code == 200

    resp = client.post("/generate/json", json=GAME_PAYLOAD)
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers


def test_generate_rate_limit_applies_to_propose_name_and_upload_too(reload_api):
    """Les 3 routes de generation partagent le meme plafond (meme cle IP) --
    pas un compteur independant par route, sinon le plafond global serait
    contournable en repartissant les requetes entre les 3."""
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE="2")
    client = TestClient(mod.app)
    assert client.post("/generate/json", json=GAME_PAYLOAD).status_code == 200
    assert client.post("/propose-name", json={"category": "video", "filenames": []}).status_code in (
        200,
        400,
    )  # 400 = pas de name_proposal configure pour ce profil/categorie ; peu importe ici, pas 429/401
    resp = client.post("/generate", data={"category": "game", "data": "{}"})
    assert resp.status_code == 429


def test_generate_rate_limit_is_per_client_ip(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE="1")
    client_a = TestClient(mod.app, client=("1.2.3.4", 12345))
    client_b = TestClient(mod.app, client=("5.6.7.8", 12345))

    assert client_a.post("/generate/json", json=GAME_PAYLOAD).status_code == 200
    assert client_a.post("/generate/json", json=GAME_PAYLOAD).status_code == 429
    # client_b n'a pas encore consomme SON quota, independant de client_a.
    assert client_b.post("/generate/json", json=GAME_PAYLOAD).status_code == 200


# --------------------------------------------------------------------------- #
# NFOGEN_TRUST_PROXY_HEADERS (priorite 3 de l'audit) : derriere le reverse
# proxy Caddy ajoute par install.sh (NFOGEN_DOMAIN/NFOGEN_LOCAL_TLS),
# request.client.host vaut toujours l'IP de Caddy (127.0.0.1) sans ceci --
# tous les clients partageraient un seul quota au lieu d'un quota par IP.
# --------------------------------------------------------------------------- #
def test_rate_limit_ignores_x_forwarded_for_by_default(reload_api):
    """Sans NFOGEN_TRUST_PROXY_HEADERS, l'en-tete est ignore (comportement
    par defaut, pas de confiance accordee a un en-tete que N'IMPORTE QUEL
    client peut fournir lui-meme sans reverse proxy devant l'API)."""
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE="1")
    client = TestClient(mod.app, client=("9.9.9.9", 12345))

    assert (
        client.post(
            "/generate/json", json=GAME_PAYLOAD, headers={"X-Forwarded-For": "1.1.1.1"}
        ).status_code
        == 200
    )
    # Meme "IP" annoncee par le client lui-meme (1.1.1.1) sur la 2e requete :
    # sans confiance dans l'en-tete, seule l'IP TCP reelle (9.9.9.9) compte,
    # donc le quota (1/min) est bien consomme -> 429.
    resp = client.post(
        "/generate/json", json=GAME_PAYLOAD, headers={"X-Forwarded-For": "2.2.2.2"}
    )
    assert resp.status_code == 429


def test_rate_limit_trusts_rightmost_x_forwarded_for_when_enabled(reload_api):
    """Avec NFOGEN_TRUST_PROXY_HEADERS=1, seule la valeur la PLUS A DROITE de
    X-Forwarded-For compte (celle ajoutee par notre reverse proxy immediat,
    jamais falsifiable par le client) -- pas la plus a gauche, que le client
    peut fixer lui-meme."""
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE="1",
        NFOGEN_TRUST_PROXY_HEADERS="1",
    )
    # Simule deux clients reels distincts derriere le MEME reverse proxy
    # (meme IP TCP source vue par uvicorn), differencies seulement par la
    # valeur ajoutee par le proxy en fin d'en-tete.
    client_a = TestClient(mod.app, client=("127.0.0.1", 12345))
    client_b = TestClient(mod.app, client=("127.0.0.1", 12345))

    assert (
        client_a.post(
            "/generate/json", json=GAME_PAYLOAD, headers={"X-Forwarded-For": "1.2.3.4"}
        ).status_code
        == 200
    )
    assert (
        client_a.post(
            "/generate/json", json=GAME_PAYLOAD, headers={"X-Forwarded-For": "1.2.3.4"}
        ).status_code
        == 429
    )
    # client_b : IP forwardee differente -> quota independant, pas encore consomme.
    assert (
        client_b.post(
            "/generate/json", json=GAME_PAYLOAD, headers={"X-Forwarded-For": "5.6.7.8"}
        ).status_code
        == 200
    )


def test_rate_limit_trusted_header_takes_rightmost_hop_not_client_supplied_prefix(reload_api):
    """Un client pourrait pre-remplir X-Forwarded-For lui-meme avant que le
    reverse proxy n'ajoute SA valeur a droite (ex. "attaquant-invente,
    vraie-ip-tcp-du-client") : seule la valeur la plus a droite doit compter,
    jamais un prefixe que le client controle entierement. Deux vraies IP TCP
    DIFFERENTES cote serveur (sinon un en-tete simplement ignore donnerait le
    meme resultat par coincidence, cf. le test precedent) : seule l'egalite
    du dernier maillon de X-Forwarded-For doit rapprocher ces deux requetes
    du meme quota."""
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE="1",
        NFOGEN_TRUST_PROXY_HEADERS="1",
    )
    client_1 = TestClient(mod.app, client=("198.51.100.1", 12345))
    client_2 = TestClient(mod.app, client=("198.51.100.2", 12345))

    assert (
        client_1.post(
            "/generate/json",
            json=GAME_PAYLOAD,
            headers={"X-Forwarded-For": "invente-par-le-client, 203.0.113.7"},
        ).status_code
        == 200
    )
    # Prefixe different, vraie IP TCP differente aussi -- mais meme dernier
    # maillon (203.0.113.7) : doit partager le meme quota (1/min), deja
    # consomme -> 429.
    resp = client_2.post(
        "/generate/json",
        json=GAME_PAYLOAD,
        headers={"X-Forwarded-For": "autre-invention, 203.0.113.7"},
    )
    assert resp.status_code == 429


def test_generate_rate_limit_window_resets_after_real_delay(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE="1")
    monkeypatch.setattr(mod, "_GENERATE_RATE_WINDOW_SECONDS", 0.15)
    client = TestClient(mod.app)
    assert client.post("/generate/json", json=GAME_PAYLOAD).status_code == 200
    assert client.post("/generate/json", json=GAME_PAYLOAD).status_code == 429

    time.sleep(0.3)
    assert client.post("/generate/json", json=GAME_PAYLOAD).status_code == 200


def test_sweep_removes_stale_generate_rate_limit_entries(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE="5")
    client = TestClient(mod.app)
    client.post("/generate/json", json=GAME_PAYLOAD)
    assert mod._GENERATE_REQUEST_LOG  # au moins une IP enregistree

    monkeypatch.setattr(mod, "_GENERATE_RATE_WINDOW_SECONDS", -1.0)  # toute entree est "hors fenetre"
    # _last_sweep=0.0 ne suffit pas a lui seul : time.monotonic() n'est PAS
    # garanti d'etre "grand" (sa reference de depart est arbitraire, ex.
    # demarrage du conteneur -- observe en CI : now ~118s, largement sous les
    # 300s de _SWEEP_INTERVAL_SECONDS, le balayage etait donc ignore alors
    # qu'il l'etait toujours sur une machine avec plus d'uptime). On neutralise
    # directement l'intervalle plutot que de deviner une valeur de _last_sweep
    # "assez ancienne".
    monkeypatch.setattr(mod, "_SWEEP_INTERVAL_SECONDS", -1.0)
    monkeypatch.setattr(mod, "_last_sweep", 0.0)
    mod._sweep_stale_entries()
    assert mod._GENERATE_REQUEST_LOG == {}


def test_auth_status_open_when_no_token_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.get("/auth/status")
    assert resp.status_code == 200
    assert resp.json() == {
        "auth_required": False,
        "authenticated": True,
        "token_login_enabled": False,
        "accounts_login_enabled": False,
        "accounts_bootstrap_available": False,
    }


def test_auth_status_requires_login_when_token_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    resp = client.get("/auth/status")
    assert resp.json() == {
        "auth_required": True,
        "authenticated": False,
        "token_login_enabled": True,
        "accounts_login_enabled": False,
        "accounts_bootstrap_available": False,
    }


def test_login_sets_httponly_session_cookie_and_unlocks_access(reload_api, tmp_path):
    """Regression : remplace le stockage du token en localStorage cote
    frontend (alerte CodeQL "Clear text storage of sensitive information").
    Le cookie pose par /login doit etre httpOnly (jamais lisible par du
    JavaScript), et doit a lui seul suffire pour passer require_token. Teste
    via /profiles/store (toujours protegee), pas /generate (ouverte par
    defaut, cf. section dediee)."""
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_PROFILES_DIR=str(tmp_path))
    client = TestClient(mod.app)

    login = client.post("/login", json={"token": "secret123"})
    assert login.status_code == 200
    cookie = next(c for c in client.cookies.jar if c.name == "nfogen_session")
    assert cookie._rest.get("HttpOnly") is not None or cookie.has_nonstandard_attr("HttpOnly")

    status = client.get("/auth/status")
    body = status.json()
    assert body["auth_required"] is True
    assert body["authenticated"] is True

    resp = client.get("/profiles/store")
    assert resp.status_code == 200


def test_login_rejects_wrong_token(reload_api, tmp_path):
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_PROFILES_DIR=str(tmp_path))
    client = TestClient(mod.app)
    resp = client.post("/login", json={"token": "mauvais"})
    assert resp.status_code == 401
    assert client.get("/profiles/store").status_code == 401


def test_login_requires_auth_to_be_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post("/login", json={"token": "peu-importe"})
    assert resp.status_code == 400


def test_logout_clears_session_cookie(reload_api, tmp_path):
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_PROFILES_DIR=str(tmp_path))
    client = TestClient(mod.app)
    client.post("/login", json={"token": "secret123"})
    assert client.get("/profiles/store").status_code == 200

    logout = client.post("/logout")
    assert logout.status_code == 200
    assert client.get("/profiles/store").status_code == 401


# --------------------------------------------------------------------------- #
# Comptes administrateurs nommes (NFOGEN_ACCOUNTS_FILE) : alternative au
# token partage, meme role unique. Voir nfogen/accounts.py.
# --------------------------------------------------------------------------- #
def test_accounts_bootstrap_open_without_auth_on_fully_open_instance(reload_api, tmp_path):
    """Le tout premier compte peut etre cree sans authentification, mais
    UNIQUEMENT si rien ne protege encore l'instance (ni token, ni compte
    existant) : equivalent a activer la protection depuis un etat
    entierement ouvert, pas a la contourner."""
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_ACCOUNTS_FILE=str(tmp_path / "accounts.json"))
    client = TestClient(mod.app)
    assert client.get("/auth/status").json()["accounts_bootstrap_available"] is True

    resp = client.post("/accounts", json={"username": "admin1", "password": "secret123"})
    assert resp.status_code == 200
    assert client.get("/auth/status").json()["accounts_bootstrap_available"] is False

    login = client.post("/login", json={"username": "admin1", "password": "secret123"})
    assert login.status_code == 200


def test_accounts_bootstrap_blocked_once_token_configured(reload_api, tmp_path):
    """Si un token est deja configure, la creation d'un compte exige une
    authentification valable -- on ne peut pas creer un acces admin
    supplementaire en contournant une protection deja active."""
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_ACCOUNTS_FILE=str(tmp_path / "accounts.json"))
    client = TestClient(mod.app)
    resp = client.post("/accounts", json={"username": "admin1", "password": "secret123"})
    assert resp.status_code == 401


def test_accounts_bootstrap_blocked_once_an_account_exists(reload_api, tmp_path):
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_ACCOUNTS_FILE=str(tmp_path / "accounts.json"))
    client = TestClient(mod.app)
    client.post("/accounts", json={"username": "admin1", "password": "secret123"})

    resp = client.post("/accounts", json={"username": "admin2", "password": "autresecret"})
    assert resp.status_code == 401


def test_accounts_bootstrap_is_not_a_race(reload_api, tmp_path):
    """Deux requetes POST /accounts concurrentes, toutes deux lancees pendant
    la fenetre de bootstrap (aucun compte encore visible), ne doivent PAS
    pouvoir creer chacune un compte sans authentification : une seule doit
    reussir, l'autre doit retomber sur `require_token` (401, puisqu'un compte
    existe desormais). Sans le verrou de `create_account_route`
    (`_ACCOUNTS_BOOTSTRAP_LOCK`), FastAPI execute les routes synchrones dans
    un threadpool -- les deux requetes pourraient lire "aucun compte" avant
    que l'une n'ait ecrit le sien, et donc toutes deux passer le controle de
    bootstrap. On elargit deliberement la fenetre de course avec un delai
    artificiel dans `accounts.list_accounts` pour rendre le test deterministe
    plutot que de dependre du hasard de l'ordonnancement des threads."""
    from concurrent.futures import ThreadPoolExecutor

    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_ACCOUNTS_FILE=str(tmp_path / "accounts.json"))
    client = TestClient(mod.app)

    original_list_accounts = mod.accounts.list_accounts

    def slow_list_accounts():
        time.sleep(0.05)
        return original_list_accounts()

    mod.accounts.list_accounts = slow_list_accounts

    def _post(username: str):
        return client.post("/accounts", json={"username": username, "password": "secret123"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_post, "admin1")
        f2 = pool.submit(_post, "admin2")
        statuses = sorted([f1.result().status_code, f2.result().status_code])

    assert statuses == [200, 401], (
        "les deux requetes concurrentes ont reussi sans authentification "
        f"(statuts obtenus : {statuses}) : la fenetre de bootstrap n'est pas verrouillee."
    )
    # Un seul des deux comptes a effectivement ete cree (peu importe lequel a
    # gagne la course) : la seconde tentative a bien ete traitee comme une
    # creation NORMALE (authentification requise), pas comme un second
    # bootstrap.
    assert len(original_list_accounts()) == 1


def test_accounts_create_requires_token_once_protected(reload_api, tmp_path):
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_ACCOUNTS_FILE=str(tmp_path / "accounts.json"))
    client = TestClient(mod.app)
    resp = client.post(
        "/accounts",
        json={"username": "admin1", "password": "secret123"},
        headers={"Authorization": "Bearer secret123"},
    )
    assert resp.status_code == 200
    assert client.get("/accounts", headers={"Authorization": "Bearer secret123"}).json() == ["admin1"]


def test_accounts_login_unlocks_profile_management(reload_api, tmp_path):
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_ACCOUNTS_FILE=str(tmp_path / "accounts.json"))
    client = TestClient(mod.app)
    client.post("/accounts", json={"username": "admin1", "password": "secret123"})

    assert client.get("/profiles/store").status_code == 401  # le simple fichier ne suffit pas

    login = client.post("/login", json={"username": "admin1", "password": "mauvais"})
    assert login.status_code == 401

    login = client.post("/login", json={"username": "admin1", "password": "secret123"})
    assert login.status_code == 200
    assert client.get("/profiles/store").status_code == 400  # NFOGEN_PROFILES_DIR absente, mais authentifie


def test_accounts_delete_revokes_active_sessions_immediately(reload_api, tmp_path):
    """L'interet de comptes distincts : revoquer UN acces precis sans
    toucher aux autres. Une session deja ouverte pour le compte supprime
    doit cesser de fonctionner immediatement, pas seulement au redemarrage."""
    mod = reload_api(
        NFOGEN_API_TOKEN="secret123",
        NFOGEN_ACCOUNTS_FILE=str(tmp_path / "accounts.json"),
        NFOGEN_PROFILES_DIR=str(tmp_path / "profiles"),
    )
    admin_client = TestClient(mod.app)
    headers = {"Authorization": "Bearer secret123"}
    admin_client.post("/accounts", json={"username": "admin1", "password": "secret123"}, headers=headers)
    # un 2e compte : supprimer le dernier compte restant est refuse (cf.
    # test_accounts_delete_refuses_last_account), il en faut un autre.
    admin_client.post("/accounts", json={"username": "admin2", "password": "autresecret"}, headers=headers)

    victim_client = TestClient(mod.app)
    victim_client.post("/login", json={"username": "admin1", "password": "secret123"})
    assert victim_client.get("/profiles/store").status_code == 200  # session valable

    admin_client.delete("/accounts/admin1", headers=headers)
    assert victim_client.get("/profiles/store").status_code == 401  # session revoquee


def test_accounts_delete_refuses_last_account(reload_api, tmp_path):
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_ACCOUNTS_FILE=str(tmp_path / "accounts.json"))
    client = TestClient(mod.app)
    headers = {"Authorization": "Bearer secret123"}
    client.post("/accounts", json={"username": "admin1", "password": "secret123"}, headers=headers)

    resp = client.delete("/accounts/admin1", headers=headers)
    assert resp.status_code == 400


def test_login_lockout_after_too_many_failed_attempts(reload_api, tmp_path):
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_ACCOUNTS_FILE=str(tmp_path / "accounts.json"))
    client = TestClient(mod.app)
    client.post("/accounts", json={"username": "admin1", "password": "secret123"})

    for _ in range(5):
        resp = client.post("/login", json={"username": "admin1", "password": "mauvais"})
        assert resp.status_code == 401

    locked = client.post("/login", json={"username": "admin1", "password": "secret123"})
    assert locked.status_code == 429


def test_login_lockout_is_per_account_not_global(reload_api, tmp_path):
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_ACCOUNTS_FILE=str(tmp_path / "accounts.json"))
    client = TestClient(mod.app)
    client.post("/accounts", json={"username": "admin1", "password": "secret123"})  # amorcage
    client.post("/login", json={"username": "admin1", "password": "secret123"})
    # cree admin2 via la session d'admin1 (aucun token configure dans ce test)
    client.post("/accounts", json={"username": "admin2", "password": "autresecret"})

    for _ in range(5):
        client.post("/login", json={"username": "admin1", "password": "mauvais"})

    # admin1 verrouille, mais admin2 doit toujours pouvoir se connecter normalement
    client2 = TestClient(mod.app)
    resp = client2.post("/login", json={"username": "admin2", "password": "autresecret"})
    assert resp.status_code == 200


def test_login_lockout_on_token_is_per_ip_not_global(reload_api):
    """Le login par token n'a qu'un seul "compte" partage : le verrou
    anti-bruteforce doit se faire par IP source, pas globalement -- sinon un
    tiers anonyme peut bloquer le login par token pour tout le monde en
    enchainant des echecs (cf. audit)."""
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    attacker = TestClient(mod.app, client=("1.2.3.4", 12345))
    victim = TestClient(mod.app, client=("5.6.7.8", 12345))

    for _ in range(5):
        resp = attacker.post("/login", json={"token": "mauvais"})
        assert resp.status_code == 401

    locked = attacker.post("/login", json={"token": "secret123"})
    assert locked.status_code == 429

    # victim, depuis une autre IP, n'est pas affecte par le verrou de attacker
    resp = victim.post("/login", json={"token": "secret123"})
    assert resp.status_code == 200


def test_login_lockout_on_token_trusts_forwarded_for_when_enabled(reload_api):
    """Le verrou par IP du login token (cf. plus haut) beneficie du meme
    en-tete de confiance : sans NFOGEN_TRUST_PROXY_HEADERS, deux clients
    reels derriere le meme reverse proxy partageraient le meme verrou."""
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_TRUST_PROXY_HEADERS="1")
    client = TestClient(mod.app, client=("127.0.0.1", 12345))

    for _ in range(5):
        resp = client.post(
            "/login", json={"token": "mauvais"}, headers={"X-Forwarded-For": "1.2.3.4"}
        )
        assert resp.status_code == 401

    # Meme IP TCP source (127.0.0.1, le reverse proxy), mais IP forwardee
    # differente -> pas affecte par le verrou de 1.2.3.4.
    resp = client.post(
        "/login", json={"token": "secret123"}, headers={"X-Forwarded-For": "5.6.7.8"}
    )
    assert resp.status_code == 200


def test_login_requires_some_credential(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post("/login", json={})
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Expiration des sessions (audit du 2026-08-11) : avant ce correctif, une
# session ne disparaissait jamais tant que le processus tournait, meme
# totalement inactive -- un cookie vole restait valable indefiniment. Deux
# mecanismes independants, testes separement : inactivite (glissante) et duree
# de vie absolue (non glissante, protege meme un cookie reutilise a intervalles
# reguliers). `_LOGIN_ATTEMPTS`/`_SESSIONS` sont aussi purges pour eviter une
# croissance non bornee (attaquant anonyme sur /login avec des identifiants
# distincts, sessions jamais reutilisees).
# --------------------------------------------------------------------------- #
def test_session_default_timeouts_match_documented_defaults(reload_api):
    """24h d'inactivite, 7 jours de duree de vie absolue -- valeurs par defaut
    sans NFOGEN_SESSION_IDLE_TIMEOUT_MINUTES/NFOGEN_SESSION_MAX_LIFETIME_HOURS."""
    mod = reload_api(NFOGEN_SESSION_IDLE_TIMEOUT_MINUTES=None, NFOGEN_SESSION_MAX_LIFETIME_HOURS=None)
    assert mod._SESSION_IDLE_TIMEOUT_SECONDS == 1440 * 60
    assert mod._SESSION_MAX_LIFETIME_SECONDS == 168 * 3600


def test_session_expires_after_real_idle_timeout(reload_api, tmp_path):
    """Bout en bout, avec un vrai delai (pas de mock d'horloge) : prouve que
    NFOGEN_SESSION_IDLE_TIMEOUT_MINUTES est bien branchee jusqu'a l'appel HTTP,
    pas seulement en isolation sur les fonctions internes ci-dessous."""
    mod = reload_api(
        NFOGEN_API_TOKEN="secret123",
        NFOGEN_PROFILES_DIR=str(tmp_path),
        NFOGEN_SESSION_IDLE_TIMEOUT_MINUTES="0.002",  # ~0.12s
    )
    client = TestClient(mod.app)
    client.post("/login", json={"token": "secret123"})
    assert client.get("/profiles/store").status_code == 200

    time.sleep(0.3)
    assert client.get("/profiles/store").status_code == 401


def test_touch_session_expires_on_idle_timeout(reload_api, monkeypatch):
    """Version deterministe (sans sleep) de la meme garantie, sur la fonction
    interne : `_touch_session` purge IMMEDIATEMENT une session expiree par
    inactivite, sans attendre le balayage periodique."""
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    resp = client.post("/login", json={"token": "secret123"})
    cookie = resp.cookies.get("nfogen_session")
    assert cookie in mod._SESSIONS

    monkeypatch.setattr(mod, "_SESSION_IDLE_TIMEOUT_SECONDS", -1.0)  # deja "expiree" par definition
    assert mod._touch_session(cookie) is False
    assert cookie not in mod._SESSIONS  # purgee immediatement, pas seulement rejetee


def test_touch_session_expires_at_max_lifetime_despite_recent_activity(reload_api, tmp_path, monkeypatch):
    """La duree de vie ABSOLUE n'est pas glissante : une session tres recemment
    utilisee (idle timeout large, donc pas expiree par inactivite) doit quand
    meme expirer si sa duree de vie totale depasse NFOGEN_SESSION_MAX_LIFETIME_HOURS."""
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_PROFILES_DIR=str(tmp_path))
    client = TestClient(mod.app)
    client.post("/login", json={"token": "secret123"})
    assert client.get("/profiles/store").status_code == 200  # rafraichit last_seen

    monkeypatch.setattr(mod, "_SESSION_MAX_LIFETIME_SECONDS", -1.0)  # deja "trop vieille" par definition
    resp = client.get("/profiles/store")
    assert resp.status_code == 401


def test_sweep_removes_stale_login_attempts(reload_api, monkeypatch):
    """`_LOGIN_ATTEMPTS` ne doit pas grossir indefiniment : une entree sans
    nouvelle tentative depuis NFOGEN_LOGIN_ATTEMPTS_TTL (ici forcee a expirer
    immediatement) est purgee par `_sweep_stale_entries`."""
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    mod._record_login_failure("un_identifiant_quelconque")
    assert "un_identifiant_quelconque" in mod._LOGIN_ATTEMPTS

    monkeypatch.setattr(mod, "_LOGIN_ATTEMPTS_TTL_SECONDS", -1.0)
    # cf. test_sweep_removes_stale_generate_rate_limit_entries : neutralise
    # l'intervalle plutot que de supposer que time.monotonic() est "grand".
    monkeypatch.setattr(mod, "_SWEEP_INTERVAL_SECONDS", -1.0)
    monkeypatch.setattr(mod, "_last_sweep", 0.0)  # contourne le throttle du balayage (300s) pour le test
    mod._sweep_stale_entries()
    assert "un_identifiant_quelconque" not in mod._LOGIN_ATTEMPTS


def test_sweep_removes_expired_sessions(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    resp = client.post("/login", json={"token": "secret123"})
    cookie = resp.cookies.get("nfogen_session")
    assert cookie in mod._SESSIONS

    monkeypatch.setattr(mod, "_SESSION_IDLE_TIMEOUT_SECONDS", -1.0)
    monkeypatch.setattr(mod, "_SWEEP_INTERVAL_SECONDS", -1.0)  # idem : cf. test ci-dessus
    monkeypatch.setattr(mod, "_last_sweep", 0.0)
    mod._sweep_stale_entries()
    assert cookie not in mod._SESSIONS


def test_sweep_is_throttled_and_does_not_scan_every_request(reload_api, monkeypatch):
    """Le balayage ne doit PAS parcourir les dicts a chaque requete (cout O(n)
    inutile) : tant que NFOGEN... _SWEEP_INTERVAL_SECONDS n'est pas ecoule
    depuis le dernier balayage, un appel supplementaire est un no-op."""
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    mod._record_login_failure("un_identifiant_quelconque")
    monkeypatch.setattr(mod, "_LOGIN_ATTEMPTS_TTL_SECONDS", -1.0)
    monkeypatch.setattr(mod, "_last_sweep", time.monotonic())  # balayage "tres recent" : throttle actif
    mod._sweep_stale_entries()
    assert "un_identifiant_quelconque" in mod._LOGIN_ATTEMPTS  # pas balaye : throttle non ecoule


def test_health_never_requires_token(reload_api):
    """/health doit rester accessible (supervision) meme avec un token configure."""
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    assert client.get("/health").status_code == 200


# --------------------------------------------------------------------------- #
# CORS
# --------------------------------------------------------------------------- #
def test_no_cors_header_by_default(reload_api):
    mod = reload_api(NFOGEN_CORS_ORIGINS=None)
    client = TestClient(mod.app)
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert "access-control-allow-origin" not in resp.headers


def test_cors_header_for_configured_origin(reload_api):
    mod = reload_api(NFOGEN_CORS_ORIGINS="http://localhost:5173")
    client = TestClient(mod.app)
    resp = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"


# --------------------------------------------------------------------------- #
# Limite de taille d'upload
# --------------------------------------------------------------------------- #
def test_rejects_oversized_payload(reload_api):
    mod = reload_api(NFOGEN_MAX_UPLOAD_MB="1")
    client = TestClient(mod.app)
    payload = {"category": "game", "data": {"title": "x" * 2_000_000, "platform": "PC"}}
    resp = client.post("/generate/json", json=payload)
    assert resp.status_code == 413


def test_accepts_payload_under_limit(reload_api):
    mod = reload_api(NFOGEN_MAX_UPLOAD_MB="1")
    client = TestClient(mod.app)
    resp = client.post("/generate/json", json=GAME_PAYLOAD)
    assert resp.status_code == 200


def test_generate_upload_enforces_real_byte_count_even_if_content_length_lies(reload_api):
    """Regression : le middleware `_limit_upload_size` ne controle que le
    Content-Length DECLARE par le client -- un client malhonnete (ou un
    transfert sans Content-Length) le contournerait entierement. Le total des
    octets REELLEMENT ecrits sur disque dans `generate_upload` doit lui aussi
    appliquer la limite, independamment de l'en-tete annonce."""
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_MAX_UPLOAD_MB="1")
    client = TestClient(mod.app)
    big = b"x" * (2 * 1024 * 1024)  # 2 Mo > plafond de 1 Mo
    resp = client.post(
        "/generate",
        data={"category": "ebook", "data": '{"title": "Test"}'},
        files={"files": ("big.bin", big, "application/octet-stream")},
        headers={"content-length": "100"},  # ment sur la taille declaree
    )
    assert resp.status_code == 413


# --------------------------------------------------------------------------- #
# Nom de fichier pour Content-Disposition : pas d'injection d'en-tete HTTP
# --------------------------------------------------------------------------- #
def test_filename_strips_crlf_from_profile_declared_name():
    """Regression : un release_name fourni par l'utilisateur peut devenir le
    nom de fichier impose par un profil (`filename_template`), qui finit
    directement dans l'en-tete Content-Disposition. uvicorn rejette une
    injection CRLF au niveau protocole (verifie manuellement), mais le code
    ne doit pas en dependre : `_filename` doit neutraliser ces caracteres
    lui-meme, quel que soit le serveur ASGI utilise."""
    name = api_module._filename("video", {}, "foo\r\nX-Evil: 1\r\n\r\n<script>")
    assert "\r" not in name
    assert "\n" not in name
    assert name == "fooX-Evil: 1<script>"


def test_filename_strips_quotes_and_backslash():
    name = api_module._filename("video", {}, 'foo".nfo\\')
    assert '"' not in name
    assert "\\" not in name


def test_filename_fallback_path_already_safe():
    name = api_module._filename("game", {"title": "foo\r\nX-Evil: 1"}, None)
    assert "\r" not in name and "\n" not in name


# --------------------------------------------------------------------------- #
# Frontend buildé optionnel (NFOGEN_FRONTEND_DIST) : pas de traversee de chemin
# --------------------------------------------------------------------------- #
def test_frontend_dist_serves_real_files(reload_api, tmp_path):
    frontend_dir = tmp_path / "dist"
    (frontend_dir / "assets").mkdir(parents=True)
    (frontend_dir / "index.html").write_text("<html>index</html>", encoding="utf-8")
    (frontend_dir / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")

    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_FRONTEND_DIST=str(frontend_dir))
    client = TestClient(mod.app)

    assert client.get("/").text == "<html>index</html>"
    assert client.get("/favicon.svg").text == "<svg></svg>"
    assert client.get("/settings").text == "<html>index</html>"  # repli SPA


def test_frontend_dist_blocks_path_traversal(reload_api, tmp_path):
    """Regression : `full_path` (issu de l'URL) etait utilise sans
    normalisation pour construire un chemin disque -- une requete comme
    `GET /../secret.txt` pouvait potentiellement lire un fichier hors du
    dossier frontend, sur une route sans authentification (alerte CodeQL,
    cf. ROADMAP.md)."""
    frontend_dir = tmp_path / "dist"
    (frontend_dir / "assets").mkdir(parents=True)
    (frontend_dir / "index.html").write_text("<html>index</html>", encoding="utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("ne doit jamais etre lisible via l'API", encoding="utf-8")

    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_FRONTEND_DIST=str(frontend_dir))
    client = TestClient(mod.app)

    for path in ("/../secret.txt", "/assets/../../secret.txt", "/%2e%2e/secret.txt"):
        resp = client.get(path)
        assert "ne doit jamais" not in resp.text, f"fuite via {path!r}"


# --------------------------------------------------------------------------- #
# Proposition de nom (POST /propose-name, noms de fichiers seuls)
# --------------------------------------------------------------------------- #
def test_propose_name_open_by_default_even_with_token_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    resp = client.post("/propose-name", json={"category": "video", "filenames": ["x.mkv"]})
    assert resp.status_code == 200


def test_propose_name_lockable_via_require_auth_for_generate(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123", NFOGEN_REQUIRE_AUTH_FOR_GENERATE="1")
    client = TestClient(mod.app)
    resp = client.post("/propose-name", json={"category": "video", "filenames": ["x.mkv"]})
    assert resp.status_code == 401


def test_propose_name_real_c411_video_convention(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    filenames = [
        "One Piece (1999) - S01E01 - 001 - Im Luffy! [WEBDL-1080p][AC3 2.0][FR+JA][x264 8bit].mkv",
        "One Piece (1999) - S01E02 - 002 - Enter Zoro! [WEBDL-1080p][AC3 2.0][FR+JA][x264 8bit].mkv",
    ]
    resp = client.post("/propose-name", json={"category": "video", "filenames": filenames})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "One.Piece.S01.MULTI.VFF.1080p.WEB.AC3.2.0.x264-NOTAG"
    assert any("équipe" in w for w in body["warnings"])


def test_propose_name_title_hint_fills_gaps_left_by_generic_filename(reload_api):
    """Le tag `Title` embarque dans le conteneur (extrait cote client, ex.
    via mediainfo.js) peut etre transmis en complement des noms de fichiers
    quand ceux-ci ne suffisent pas a determiner la resolution/le codec/l'equipe."""
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post(
        "/propose-name",
        json={
            "category": "video",
            "filenames": ["One Piece - S01E01 - 001 - Im Luffy!.mkv"],
            "title_hints": ["One Piece S01 ''Arc Morgan'' WebDl 1080p x264 - Chris44"],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fields"]["resolution"] == "1080"
    assert body["fields"]["video_codec"] == "x264"
    assert body["fields"]["team"] == "Chris44"


def test_propose_name_unsupported_profile_category_is_400(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post("/propose-name", json={"category": "audio", "filenames": ["x.flac"]})
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Upload multipart : nom de fichier "speciaux" sans crash
# --------------------------------------------------------------------------- #
def test_generate_upload_filename_dotdot_does_not_crash(reload_api):
    """Regression : Path("..").name vaut litteralement ".." (pas une chaine
    vide) -- un fichier uploade nomme ".." ecrivait dans le PARENT du dossier
    temporaire (IsADirectoryError non rattrapee -> erreur serveur brute)."""
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post(
        "/generate",
        data={"category": "ebook", "data": '{"title": "Test"}'},
        files={"files": ("..", b"contenu", "application/octet-stream")},
    )
    assert resp.status_code == 200


def test_generate_upload_filename_dot_does_not_crash(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post(
        "/generate",
        data={"category": "ebook", "data": '{"title": "Test"}'},
        files={"files": (".", b"contenu", "application/octet-stream")},
    )
    assert resp.status_code == 200


# --------------------------------------------------------------------------- #
# Separation erreurs 400 (client) / 500 (serveur, sans fuite de details)
# --------------------------------------------------------------------------- #
def test_run_generate_translates_value_error_to_400(monkeypatch):
    monkeypatch.setattr(
        api_module.engine, "generate", lambda **_: (_ for _ in ()).throw(ValueError("message clair"))
    )
    with pytest.raises(api_module.HTTPException) as exc_info:
        api_module._run_generate()
    assert exc_info.value.status_code == 400
    assert "message clair" in exc_info.value.detail


def test_run_generate_hides_unexpected_error_as_500(monkeypatch):
    monkeypatch.setattr(
        api_module.engine,
        "generate",
        lambda **_: (_ for _ in ()).throw(RuntimeError("secret interne tres prive")),
    )
    with pytest.raises(api_module.HTTPException) as exc_info:
        api_module._run_generate()
    assert exc_info.value.status_code == 500
    assert "secret interne" not in exc_info.value.detail


def test_unknown_category_is_400_via_http(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post(
        "/generate/json", json={"category": "video", "profile": "inconnu", "data": {"raw_text": "x"}}
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Gestion de profils utilisateur (/profiles/store*)
# --------------------------------------------------------------------------- #
MANAGED_RULES = {
    "game": {
        "requires_field": "release_name",
        "doc": "doc de test",
        "example": "Mon.Jeu-TEAM",
        "tokens": [{"name": "team", "pattern": r"-[A-Z]+$", "level": "required", "error": "team manquante"}],
        "filename_template": "{release_name}.nfo",
    }
}
MANAGED_TEMPLATES = {"game": "{{ title }} - {{ release_name }}"}


@pytest.fixture(autouse=True)
def _cleanup_managed_profiles():
    yield
    for name in ("monprofil", "clone"):
        unregister_profile(name)


def test_store_requires_profiles_dir_configured(reload_api):
    mod = reload_api(NFOGEN_PROFILES_DIR=None, NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.get("/profiles/store")
    assert resp.status_code == 400


def test_store_requires_token_when_configured(reload_api, tmp_path):
    mod = reload_api(NFOGEN_PROFILES_DIR=str(tmp_path), NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    assert client.get("/profiles/store").status_code == 401
    resp = client.get("/profiles/store", headers={"Authorization": "Bearer secret123"})
    assert resp.status_code == 200


def test_store_full_crud_flow(reload_api, tmp_path):
    mod = reload_api(NFOGEN_PROFILES_DIR=str(tmp_path), NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)

    create = client.put(
        "/profiles/store/monprofil", json={"rules": MANAGED_RULES, "templates": MANAGED_TEMPLATES}
    )
    assert create.status_code == 200

    assert client.get("/profiles/store").json() == ["monprofil"]

    read = client.get("/profiles/store/monprofil")
    assert read.status_code == 200
    assert read.json()["rules"] == MANAGED_RULES

    delete = client.delete("/profiles/store/monprofil")
    assert delete.status_code == 200
    assert client.get("/profiles/store").json() == []


def test_store_write_invalid_schema_is_400(reload_api, tmp_path):
    mod = reload_api(NFOGEN_PROFILES_DIR=str(tmp_path), NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.put(
        "/profiles/store/monprofil", json={"rules": {"game": {"unknown_key": True}}, "templates": {}}
    )
    assert resp.status_code == 400


def test_store_export_then_import(reload_api, tmp_path):
    mod = reload_api(NFOGEN_PROFILES_DIR=str(tmp_path), NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    client.put("/profiles/store/monprofil", json={"rules": MANAGED_RULES, "templates": MANAGED_TEMPLATES})

    export = client.get("/profiles/store/monprofil/export")
    assert export.status_code == 200
    assert export.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        assert "rules.json" in zf.namelist()
        assert "templates/game.j2" in zf.namelist()

    imported = client.post(
        "/profiles/store/clone/import",
        files={"file": ("monprofil.zip", export.content, "application/zip")},
    )
    assert imported.status_code == 200
    assert client.get("/profiles/store/clone").json()["rules"] == MANAGED_RULES


def test_store_read_unknown_profile_is_400(reload_api, tmp_path):
    mod = reload_api(NFOGEN_PROFILES_DIR=str(tmp_path), NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.get("/profiles/store/inexistant")
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Profil livre avec le paquet (C411) : lisible et modifiable comme un profil
# utilisateur normal via /profiles/store/c411 (surcharge du meme nom, cf.
# nfogen/profiles/__init__.py et profile_store.py).
# --------------------------------------------------------------------------- #
def test_store_reads_builtin_c411_without_prior_override(reload_api, tmp_path):
    mod = reload_api(NFOGEN_PROFILES_DIR=str(tmp_path), NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.get("/profiles/store/c411")
    assert resp.status_code == 200
    assert "video" in resp.json()["rules"]
    assert client.get("/profiles/store").json() == []  # pas (encore) un profil GERE


def test_store_can_override_then_restore_builtin_c411(reload_api, tmp_path):
    """L'admin peut modifier C411 'dans tous les cas' (token valide) : PUT
    sur /profiles/store/c411 le surcharge comme n'importe quel profil
    utilisateur ; DELETE restaure ensuite la version livree avec le paquet."""
    mod = reload_api(NFOGEN_PROFILES_DIR=str(tmp_path), NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)

    original = client.get("/profiles/store/c411").json()["rules"]

    put = client.put("/profiles/store/c411", json={"rules": MANAGED_RULES, "templates": MANAGED_TEMPLATES})
    assert put.status_code == 200
    assert client.get("/profiles/store/c411").json()["rules"] == MANAGED_RULES
    assert client.get("/profiles/store").json() == ["c411"]

    delete = client.delete("/profiles/store/c411")
    assert delete.status_code == 200
    assert client.get("/profiles/store").json() == []
    assert client.get("/profiles/store/c411").json()["rules"] == original


# --------------------------------------------------------------------------- #
# /gapscan/* : proteges comme /profiles/store* (meme modele, cf. GAPSCAN.md).
# Clients C411/Sonarr/Radarr remplaces par des doubles de test (pas de reseau
# reel) via monkeypatch des classes importees dans nfogen.api.
# --------------------------------------------------------------------------- #
class _FakeGapscanC411:
    def __init__(self, *args, **kwargs):
        self.closed = False

    def search_movie(self, query=None, imdb_id=None, tmdb_id=None):
        return []

    def search_tv(self, query=None, imdb_id=None, tmdb_id=None, season=None, ep=None):
        return []

    def close(self):
        self.closed = True


class _FakeGapscanRadarr:
    gate: object = None

    def __init__(self, *args, **kwargs):
        self.closed = False

    def list_movie_files(self):
        if self.gate is not None:
            self.gate.wait(timeout=5)
        return [RadarrMovieFile(movie_id=1, title="Matrix", year=1999, imdb_id="tt0133093", tmdb_id=603)]

    def close(self):
        self.closed = True


class _FakeGapscanC411Covered(_FakeGapscanC411):
    """Renvoie toujours une release couvrant exactement 'Matrix' -- utilise
    pour verifier le mode incremental (POST /gapscan/run?incremental=true)."""

    def search_movie(self, query=None, imdb_id=None, tmdb_id=None):
        return [TorznabRelease(title="Matrix", guid="g", link="https://c411.org/x", imdb_id="tt0133093")]


class _FakeGapscanSonarr:
    def __init__(self, *args, **kwargs):
        self.closed = False

    def list_season_files(self):
        return [
            SonarrSeasonFile(
                series_id=1, title="Breaking Bad", year=2008, tvdb_id=81189, imdb_id="tt0903747",
                season_number=1, episode_file_count=1,
            )
        ]

    def close(self):
        self.closed = True


def _patch_gapscan_clients(monkeypatch, mod, radarr_cls=_FakeGapscanRadarr, sonarr_cls=None):
    monkeypatch.setattr(mod, "TorznabClient", _FakeGapscanC411)
    monkeypatch.setattr(mod, "RadarrClient", radarr_cls)
    if sonarr_cls is not None:
        monkeypatch.setattr(mod, "SonarrClient", sonarr_cls)


def _wait_gapscan_done(client, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        status = client.get("/gapscan/status").json()
        if status["state"] != "running":
            return status
        if time.monotonic() > deadline:
            raise TimeoutError("le scan de test ne s'est jamais termine")
        time.sleep(0.01)


def test_gapscan_routes_return_501_when_extra_not_installed(reload_api, monkeypatch):
    """nfogen[api] sans nfogen[gapscan] (httpx absent) doit continuer a
    demarrer normalement -- seules les routes /gapscan/* deviennent
    indisponibles, avec un message explicite plutot qu'une ImportError."""
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(mod, "_GAPSCAN_AVAILABLE", False)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/run")
    assert resp.status_code == 501
    assert "gapscan" in resp.json()["detail"].lower()


def test_gapscan_routes_require_auth_when_token_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    assert client.get("/gapscan/config").status_code == 401
    assert client.post("/gapscan/run").status_code == 401
    assert client.get("/gapscan/status").status_code == 401
    assert client.get("/gapscan/results").status_code == 401


def test_gapscan_config_reports_which_services_are_configured(reload_api):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_C411_API_KEY="x",
        NFOGEN_SONARR_URL=None,
        NFOGEN_SONARR_API_KEY=None,
        NFOGEN_RADARR_URL="http://radarr.local",
        NFOGEN_RADARR_API_KEY="y",
    )
    client = TestClient(mod.app)
    resp = client.get("/gapscan/config")
    assert resp.status_code == 200
    assert resp.json() == {
        "profile": "c411",
        "tracker_configured": True,
        "tracker_base_url": "https://c411.org",
        "sonarr_configured": False,
        "sonarr_url": None,
        "radarr_configured": True,
        "radarr_url": "http://radarr.local",
        "sonarr_path_mappings": {},
        "radarr_path_mappings": {},
        "tracker_announce_url_configured": False,
        "staging_dir": None,
    }
    # jamais la cle elle-meme dans la reponse, meme par accident.
    assert "x" not in resp.text and "y" not in resp.text


def test_gapscan_config_get_defaults_to_c411_profile(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.get("/gapscan/config")
    assert resp.status_code == 200
    assert resp.json()["profile"] == "c411"


def test_gapscan_config_get_accepts_a_profile_query_param(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.get("/gapscan/config", params={"profile": "ygg"})
    assert resp.status_code == 200
    assert resp.json()["profile"] == "ygg"
    assert resp.json()["tracker_configured"] is False  # rien configure pour ce profil


def test_gapscan_config_write_then_read_back(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)

    put = client.put(
        "/gapscan/config",
        json={"tracker_api_key": "secret", "sonarr_url": "http://sonarr.local", "sonarr_api_key": "sk"},
    )
    assert put.status_code == 200
    assert "secret" not in put.text and "sk" not in put.text  # jamais la cle en retour

    status = client.get("/gapscan/config").json()
    assert status["tracker_configured"] is True
    assert status["sonarr_configured"] is True
    assert status["sonarr_url"] == "http://sonarr.local"


def test_gapscan_config_write_uses_tracker_field_names(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)

    resp = client.put(
        "/gapscan/config",
        json={"profile": "c411", "tracker_api_key": "secret", "tracker_base_url": "https://c411.org"},
    )
    assert resp.status_code == 200
    assert resp.json()["tracker_configured"] is True
    assert "secret" not in resp.text


def test_gapscan_config_write_accepts_a_profile_field(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)

    put = client.put(
        "/gapscan/config",
        json={"profile": "ygg", "tracker_api_key": "ygg-key", "tracker_base_url": "https://ygg.example"},
    )
    assert put.status_code == 200
    assert put.json()["profile"] == "ygg"
    assert put.json()["tracker_configured"] is True

    # Le profil c411 (defaut) n'a rien recu de ce PUT -- namespaces separement.
    assert client.get("/gapscan/config").json()["tracker_configured"] is False


def test_gapscan_config_write_without_config_file_env_var_returns_400(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_GAPSCAN_CONFIG_FILE=None)
    client = TestClient(mod.app)
    resp = client.put("/gapscan/config", json={"tracker_api_key": "x"})
    assert resp.status_code == 400


def test_gapscan_config_partial_write_preserves_other_fields(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)

    client.put("/gapscan/config", json={"tracker_api_key": "secret"})
    client.put("/gapscan/config", json={"sonarr_url": "http://sonarr.local", "sonarr_api_key": "sk"})

    status = client.get("/gapscan/config").json()
    assert status["tracker_configured"] is True  # pas efface par le 2e PUT
    assert status["sonarr_configured"] is True


def test_gapscan_config_write_then_read_back_path_mappings(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)

    put = client.put(
        "/gapscan/config",
        json={"radarr_path_mappings": {"/data/movies": "/mnt/nas/movies"}},
    )
    assert put.status_code == 200
    assert put.json()["radarr_path_mappings"] == {"/data/movies": "/mnt/nas/movies"}

    status = client.get("/gapscan/config").json()
    assert status["radarr_path_mappings"] == {"/data/movies": "/mnt/nas/movies"}
    assert status["sonarr_path_mappings"] == {}


def test_gapscan_config_write_then_read_back_announce_url_and_staging_dir(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)

    put = client.put(
        "/gapscan/config",
        json={
            "tracker_announce_url": "https://c411.org/announce/SECRET",
            "staging_dir": "/data/staging",
        },
    )
    assert put.status_code == 200
    assert put.json()["tracker_announce_url_configured"] is True
    assert put.json()["staging_dir"] == "/data/staging"
    assert "SECRET" not in put.text  # jamais l'URL en clair, meme dans la reponse du PUT

    status = client.get("/gapscan/config").json()
    assert status["tracker_announce_url_configured"] is True
    assert status["staging_dir"] == "/data/staging"


# --------------------------------------------------------------------------- #
# Preparation d'upload (POST /gapscan/prepare-upload/preview, /commit --
# AUTOMATION.md sous-projet 4)
# --------------------------------------------------------------------------- #
def test_prepare_upload_routes_require_gapscan_available(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(mod, "_GAPSCAN_AVAILABLE", False)
    client = TestClient(mod.app)
    assert client.post("/gapscan/prepare-upload/preview", json={"local_paths": []}).status_code == 501
    assert (
        client.post("/gapscan/prepare-upload/commit", json={"release_name": "x", "files": []}).status_code
        == 501
    )
    assert client.get("/gapscan/commit-jobs").status_code == 501
    assert client.get("/gapscan/commit-jobs/x").status_code == 501
    assert client.post("/gapscan/commit-jobs/x/cancel").status_code == 501


def test_prepare_upload_routes_require_auth_when_token_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    assert client.post("/gapscan/prepare-upload/preview", json={"local_paths": []}).status_code == 401
    assert (
        client.post("/gapscan/prepare-upload/commit", json={"release_name": "x", "files": []}).status_code
        == 401
    )
    assert client.get("/gapscan/commit-jobs").status_code == 401
    assert client.get("/gapscan/commit-jobs/x").status_code == 401
    assert client.post("/gapscan/commit-jobs/x/cancel").status_code == 401


def test_prepare_upload_preview_empty_paths_returns_empty_list(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/prepare-upload/preview", json={"local_paths": []})
    assert resp.status_code == 200
    assert resp.json() == []


def test_prepare_upload_preview_real_c411_profile(reload_api):
    """Bout-en-bout via l'API : pas de fichier reel necessaire, MediaInfo
    echouera sur un chemin inexistant (extraction best-effort, voir
    upload_prep.preview_upload) mais le nommage/groupement fonctionnent
    quand meme sur le nom de fichier seul."""
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post(
        "/gapscan/prepare-upload/preview",
        json={"local_paths": ["/media/Kaamelott.2005.VFF.1080p.BluRay.AC3.x264-Dam.mkv"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["release_name"].startswith("Kaamelott")
    assert body[0]["files"][0]["source_path"] == "/media/Kaamelott.2005.VFF.1080p.BluRay.AC3.x264-Dam.mkv"


def test_prepare_upload_preview_title_override(reload_api):
    """Cas reel (2026-08-28) : le titre Sonarr/Radarr ne correspond pas au
    titre officiel attendu par C411 -- override manuel."""
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post(
        "/gapscan/prepare-upload/preview",
        json={
            "local_paths": ["/media/A.Guy.And.A.Girl.S02E01.1080p.WEB.AC3.x264-Valentin.mkv"],
            "title_override": "Un Gars, Une Fille",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["release_name"].startswith("Un.Gars.Une.Fille.")


def test_prepare_upload_commit_without_staging_dir_is_400(reload_api, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json")
    )
    client = TestClient(mod.app)
    resp = client.post(
        "/gapscan/prepare-upload/commit",
        json={"release_name": "X", "files": [{"source_path": "/x.mkv", "staged_name": "X.mkv"}]},
    )
    assert resp.status_code == 400
    assert "scène" in resp.json()["detail"] or "scene" in resp.json()["detail"].lower()


def test_prepare_upload_commit_real_flow(reload_api, tmp_path):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    source = tmp_path / "source.mkv"
    source.write_bytes(b"contenu de test")

    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json")
    )
    client = TestClient(mod.app)
    put = client.put(
        "/gapscan/config",
        json={
            "tracker_announce_url": "https://c411.example/announce/abc123",
            "staging_dir": str(staging_dir),
        },
    )
    assert put.status_code == 200

    resp = client.post(
        "/gapscan/prepare-upload/commit",
        json={
            "release_name": "Movie.2020.1080p.x264-TEAM",
            "files": [{"source_path": str(source), "staged_name": "Movie.2020.1080p.x264-TEAM.mkv"}],
        },
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert job_id

    deadline = time.monotonic() + 5.0
    status = None
    while time.monotonic() < deadline:
        status = client.get(f"/gapscan/commit-jobs/{job_id}").json()
        if status["state"] in ("done", "error", "cancelled"):
            break
        time.sleep(0.01)

    assert status["state"] == "done"
    body = status["result"]
    assert body["release_name"] == "Movie.2020.1080p.x264-TEAM"
    assert body["staged_path"] == str(staging_dir / "Movie.2020.1080p.x264-TEAM.mkv")
    assert body["torrent_path"] == str(staging_dir / "Movie.2020.1080p.x264-TEAM.torrent")
    assert body["nfo_path"] == str(staging_dir / "Movie.2020.1080p.x264-TEAM.nfo")
    assert (staging_dir / "Movie.2020.1080p.x264-TEAM.nfo").is_file()


def test_commit_job_status_404_for_unknown_job(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.get("/gapscan/commit-jobs/does-not-exist")
    assert resp.status_code == 404


def test_commit_jobs_list_is_empty_initially(reload_api):
    # commit_job_runner est un singleton de module (comme gapscan_runner),
    # pas reinitialise par reload_api -- rechargement explicite ici pour
    # partir d'un registre vierge, independamment de l'ordre des tests.
    mod = reload_api(NFOGEN_API_TOKEN=None)
    importlib.reload(mod.commit_job_runner)
    client = TestClient(mod.app)
    resp = client.get("/gapscan/commit-jobs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_cancel_unknown_job_is_404(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/commit-jobs/does-not-exist/cancel")
    assert resp.status_code == 404


def test_cancel_already_finished_job_is_409(reload_api, tmp_path):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    source = tmp_path / "source.mkv"
    source.write_bytes(b"contenu")

    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json")
    )
    client = TestClient(mod.app)
    client.put(
        "/gapscan/config",
        json={
            "tracker_announce_url": "https://c411.example/announce/abc123",
            "staging_dir": str(staging_dir),
        },
    )
    resp = client.post(
        "/gapscan/prepare-upload/commit",
        json={"release_name": "X", "files": [{"source_path": str(source), "staged_name": "X.mkv"}]},
    )
    job_id = resp.json()["job_id"]

    deadline = time.monotonic() + 5.0
    status = {"state": "staging"}
    while time.monotonic() < deadline and status["state"] not in ("done", "error", "cancelled"):
        status = client.get(f"/gapscan/commit-jobs/{job_id}").json()
        time.sleep(0.01)

    cancel_resp = client.post(f"/gapscan/commit-jobs/{job_id}/cancel")
    assert cancel_resp.status_code == 409


def test_prepare_upload_send_creates_a_draft(reload_api, tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(
        mod.upload_prep, "send_to_tracker",
        lambda **kwargs: mod.upload_prep.SendResult(draft_id=555, draft_url="https://c411.org/user/drafts/555"),
    )
    client = TestClient(mod.app)

    resp = client.post(
        "/gapscan/prepare-upload/send",
        json={
            "release_name": "Movie.2020.BluRay-TEAM",
            "staged_path": str(staged), "torrent_path": str(torrent), "nfo_path": str(nfo),
            "profile": "c411", "media_type": "movie", "radarr_movie_id": 42, "tmdb_id": 603,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["draft_id"] == 555
    assert body["draft_url"] == "https://c411.org/user/drafts/555"
    assert body["duplicate_warning"] is None


def test_prepare_upload_send_requires_auth_when_token_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    resp = client.post("/gapscan/prepare-upload/send", json={
        "release_name": "X", "staged_path": "/x.mkv", "torrent_path": "/x.torrent", "nfo_path": "/x.nfo",
    })
    assert resp.status_code == 401


def test_prepare_upload_send_requires_gapscan_available(reload_api, monkeypatch):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    monkeypatch.setattr(mod, "_GAPSCAN_AVAILABLE", False)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/prepare-upload/send", json={
        "release_name": "X", "staged_path": "/x.mkv", "torrent_path": "/x.torrent", "nfo_path": "/x.nfo",
    })
    assert resp.status_code == 501


def test_gapscan_run_rejects_when_c411_not_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY=None)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/run")
    assert resp.status_code == 400


def test_gapscan_run_rejects_when_neither_sonarr_nor_radarr_configured(reload_api):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_SONARR_URL=None, NFOGEN_RADARR_URL=None,
    )
    client = TestClient(mod.app)
    resp = client.post("/gapscan/run")
    assert resp.status_code == 400


def test_gapscan_run_rejects_only_movies_when_radarr_not_configured(reload_api, monkeypatch):
    """Bug reel trouve en audit (2026-08-27) : Sonarr seul configure +
    `only=movies` faisait "reussir" un scan de 0 titre en silence (aucune
    des deux bibliotheques n'etait interrogee), au lieu de signaler que
    `only=movies` n'a pas de sens sans Radarr."""
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_SONARR_URL="http://sonarr.local", NFOGEN_SONARR_API_KEY="y",
        NFOGEN_RADARR_URL=None,
    )
    _patch_gapscan_clients(monkeypatch, mod, sonarr_cls=_FakeGapscanSonarr)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/run", params={"only": "movies"})
    assert resp.status_code == 400


def test_gapscan_run_rejects_only_series_when_sonarr_not_configured(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
        NFOGEN_SONARR_URL=None,
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/run", params={"only": "series"})
    assert resp.status_code == 400


def test_gapscan_run_then_status_then_results(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)

    run = client.post("/gapscan/run")
    assert run.status_code == 200

    status = _wait_gapscan_done(client)
    assert status["state"] == "done"
    assert status["total"] == 1
    assert status["processed"] == 1

    body = client.get("/gapscan/results").json()
    assert body["total"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["media_type"] == "movie"
    assert body["items"][0]["title"] == "Matrix"
    assert body["items"][0]["status"] == "absent"  # FakeGapscanC411 ne renvoie jamais de match


def test_gapscan_run_uses_a_rate_limit_safe_default_interval(reload_api, monkeypatch):
    """15 requetes/min confirmees directement par les admins C411
    (2026-08-27) -- l'intervalle par defaut doit rester strictement sous ce
    seuil (60/15 = 4s pile), avec marge (4.5s -> ~13,3/min)."""
    captured: dict = {}

    class CapturingC411(_FakeGapscanC411):
        def __init__(self, *args, **kwargs):
            captured.update(kwargs)
            super().__init__(*args, **kwargs)

    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
        NFOGEN_C411_MIN_INTERVAL_SECONDS=None,
    )
    monkeypatch.setattr(mod, "TorznabClient", CapturingC411)
    monkeypatch.setattr(mod, "RadarrClient", _FakeGapscanRadarr)
    client = TestClient(mod.app)

    client.post("/gapscan/run")

    assert captured["min_interval_seconds"] >= 4.0


def test_gapscan_run_only_movies_excludes_series(reload_api, monkeypatch):
    """`?only=movies` (retour utilisateur, 2026-08-27) : scanne Radarr sans
    interroger Sonarr, meme quand les deux sont configures."""
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
        NFOGEN_SONARR_URL="http://sonarr.local", NFOGEN_SONARR_API_KEY="z",
    )
    _patch_gapscan_clients(monkeypatch, mod, sonarr_cls=_FakeGapscanSonarr)
    client = TestClient(mod.app)

    run = client.post("/gapscan/run", params={"only": "movies"})
    assert run.status_code == 200
    _wait_gapscan_done(client)

    body = client.get("/gapscan/results").json()
    assert {r["media_type"] for r in body["items"]} == {"movie"}


def test_gapscan_run_rejects_an_invalid_only_value(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)
    resp = client.post("/gapscan/run", params={"only": "bogus"})
    assert resp.status_code == 400


def test_gapscan_run_reads_the_incremental_max_age_env_var(reload_api, monkeypatch):
    """`NFOGEN_GAPSCAN_INCREMENTAL_MAX_AGE_DAYS` (retour utilisateur,
    2026-08-27 : C411 retire/ajoute des torrents assez souvent) -- converti
    en secondes et transmis a gapscan_runner.start() seulement quand
    incremental=true."""
    captured: dict = {}

    def fake_start(
        c411, radarr=None, sonarr=None, incremental=False, only=None, max_age_seconds=None,
        sonarr_path_mappings=None, radarr_path_mappings=None,
    ):
        captured["max_age_seconds"] = max_age_seconds
        return True

    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
        NFOGEN_GAPSCAN_INCREMENTAL_MAX_AGE_DAYS="3",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    monkeypatch.setattr(mod.gapscan_runner, "start", fake_start)
    client = TestClient(mod.app)

    resp = client.post("/gapscan/run", params={"incremental": "true"})
    assert resp.status_code == 200
    assert captured["max_age_seconds"] == 3 * 86400


def test_gapscan_run_passes_configured_path_mappings_to_the_runner(reload_api, monkeypatch, tmp_path):
    captured: dict = {}

    def fake_start(
        c411, radarr=None, sonarr=None, incremental=False, only=None, max_age_seconds=None,
        sonarr_path_mappings=None, radarr_path_mappings=None,
    ):
        captured["radarr_path_mappings"] = radarr_path_mappings
        captured["sonarr_path_mappings"] = sonarr_path_mappings
        return True

    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
    )
    client = TestClient(mod.app)
    client.put("/gapscan/config", json={"radarr_path_mappings": {"/data/movies": "/mnt/nas/movies"}})
    _patch_gapscan_clients(monkeypatch, mod)
    monkeypatch.setattr(mod.gapscan_runner, "start", fake_start)

    resp = client.post("/gapscan/run")

    assert resp.status_code == 200
    assert captured["radarr_path_mappings"] == {"/data/movies": "/mnt/nas/movies"}
    assert captured["sonarr_path_mappings"] == {}


def test_gapscan_run_incremental_reuses_covered_results(reload_api, monkeypatch):
    """POST /gapscan/run?incremental=true : un titre COVERED au scan
    precedent est repris tel quel, sans reinterroger C411 -- retour
    utilisateur, 2026-08-26 (voir gapscan_runner.py)."""
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    monkeypatch.setattr(mod, "RadarrClient", _FakeGapscanRadarr)
    monkeypatch.setattr(mod, "TorznabClient", _FakeGapscanC411Covered)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    status = _wait_gapscan_done(client)
    assert status["state"] == "done"
    assert client.get("/gapscan/results").json()["items"][0]["status"] == "covered"

    # Si reinterroge, ce client renverrait ABSENT (aucun match) : revelateur.
    monkeypatch.setattr(mod, "TorznabClient", _FakeGapscanC411)
    run2 = client.post("/gapscan/run", params={"incremental": "true"})
    assert run2.status_code == 200
    status2 = _wait_gapscan_done(client)
    assert status2["state"] == "done"
    assert client.get("/gapscan/results").json()["items"][0]["status"] == "covered"


def test_gapscan_results_filterable_by_status_query_param(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    _wait_gapscan_done(client)

    assert client.get("/gapscan/results", params={"status": "absent"}).json()["total"] == 1
    assert client.get("/gapscan/results", params={"status": "covered"}).json() == {"items": [], "total": 0}


class _FakeGapscanRadarrThreeMovies(_FakeGapscanRadarr):
    def list_movie_files(self):
        return [
            RadarrMovieFile(movie_id=1, title="A", year=1999, imdb_id="tt1", tmdb_id=1),
            RadarrMovieFile(movie_id=2, title="B", year=1999, imdb_id="tt2", tmdb_id=2),
            RadarrMovieFile(movie_id=3, title="C", year=1999, imdb_id="tt3", tmdb_id=3),
        ]


def test_gapscan_results_paginated(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod, radarr_cls=_FakeGapscanRadarrThreeMovies)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    _wait_gapscan_done(client)

    page1 = client.get("/gapscan/results", params={"page": 1, "page_size": 2}).json()
    assert page1["total"] == 3
    assert len(page1["items"]) == 2

    page2 = client.get("/gapscan/results", params={"page": 2, "page_size": 2}).json()
    assert page2["total"] == 3
    assert len(page2["items"]) == 1


def test_gapscan_results_filterable_by_media_type_and_genre(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    _wait_gapscan_done(client)

    assert client.get("/gapscan/results", params={"media_type": "movie"}).json()["total"] == 1
    assert client.get("/gapscan/results", params={"media_type": "series"}).json()["total"] == 0
    assert client.get("/gapscan/results", params={"genre": "anime"}).json() == {"items": [], "total": 0}


def test_gapscan_results_genre_filter_uses_the_given_profile(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )

    class _AnimeC411(_FakeGapscanC411):
        def search_movie(self, query=None, imdb_id=None, tmdb_id=None):
            return [TorznabRelease(title="Matrix", guid="g", link="https://c411.org/x", category="2060")]

    monkeypatch.setattr(mod, "RadarrClient", _FakeGapscanRadarr)
    monkeypatch.setattr(mod, "TorznabClient", _AnimeC411)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    _wait_gapscan_done(client)

    # Aucune section "tracker" declaree pour 'other' : jamais de genre.
    assert client.get("/gapscan/results", params={"genre": "anime", "profile": "other"}).json() == {
        "items": [], "total": 0
    }
    assert client.get("/gapscan/results", params={"genre": "anime"}).json()["total"] == 1


def test_gapscan_results_items_include_genre_field(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    _wait_gapscan_done(client)

    body = client.get("/gapscan/results").json()
    assert body["items"][0]["genre"] is None  # FakeGapscanC411 : aucun match -> pas de genre


def test_gapscan_results_export_csv(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    _wait_gapscan_done(client)

    resp = client.get("/gapscan/results/export.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "Matrix" in resp.text
    assert resp.text.splitlines()[0].startswith("media_type,")


def test_gapscan_results_export_csv_includes_genre_column_and_filters(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)

    client.post("/gapscan/run")
    _wait_gapscan_done(client)

    resp = client.get("/gapscan/results/export.csv")
    assert resp.status_code == 200
    header = resp.text.splitlines()[0]
    assert "genre" in header.split(",")

    filtered = client.get("/gapscan/results/export.csv", params={"media_type": "series"})
    assert filtered.status_code == 200
    assert len(filtered.text.splitlines()) == 1  # seulement l'en-tete, aucun resultat serie


def test_gapscan_run_returns_409_when_a_scan_is_already_running(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    gate_event = threading.Event()

    class _GatedRadarr(_FakeGapscanRadarr):
        gate = gate_event

    _patch_gapscan_clients(monkeypatch, mod, radarr_cls=_GatedRadarr)
    client = TestClient(mod.app)

    first = client.post("/gapscan/run")
    assert first.status_code == 200

    second = client.post("/gapscan/run")
    assert second.status_code == 409

    gate_event.set()
    _wait_gapscan_done(client)


def test_gapscan_run_accepts_a_profile_query_param(reload_api, monkeypatch, tmp_path):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_GAPSCAN_CONFIG_FILE=str(tmp_path / "gapscan_config.json"),
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    client = TestClient(mod.app)
    put = client.put(
        "/gapscan/config",
        json={"profile": "ygg", "tracker_api_key": "k", "tracker_base_url": "https://ygg.example"},
    )
    assert put.status_code == 200
    _patch_gapscan_clients(monkeypatch, mod)

    resp = client.post("/gapscan/run", params={"profile": "ygg"})
    assert resp.status_code == 200
    _wait_gapscan_done(client)


def test_gapscan_run_defaults_to_c411_profile_when_none_given(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None, NFOGEN_C411_API_KEY="x",
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    _patch_gapscan_clients(monkeypatch, mod)
    client = TestClient(mod.app)

    resp = client.post("/gapscan/run")
    assert resp.status_code == 200
    _wait_gapscan_done(client)
