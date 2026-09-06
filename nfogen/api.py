"""Service HTTP (FastAPI) pour la generation automatisee de NFO.

Lancer : nfogen serve (ou directement : uvicorn nfogen.api:app --host 0.0.0.0 --port 8000)

Variables d'environnement (toutes optionnelles ; details dans README.md) :
    NFOGEN_API_TOKEN                      token admin partage
    NFOGEN_ACCOUNTS_FILE                  comptes admin nommes (alternative au token)
    NFOGEN_REQUIRE_AUTH_FOR_GENERATE       "1" pour proteger aussi /generate*
    NFOGEN_CORS_ORIGINS                   origines cross-origin autorisees
    NFOGEN_MAX_UPLOAD_MB                  plafond de taille d'upload
    NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE plafond de requetes/min par IP sur /generate*
    NFOGEN_PROFILES_DIR                   dossier de profils utilisateur
    NFOGEN_FRONTEND_DIST                  sert aussi le frontend build
    NFOGEN_LOG_LEVEL                      niveau de logging (defaut INFO)
    NFOGEN_SESSION_IDLE_TIMEOUT_MINUTES   expiration de session par inactivite (defaut 1440)
    NFOGEN_SESSION_MAX_LIFETIME_HOURS     duree de vie absolue d'une session (defaut 168)
    NFOGEN_COOKIE_SECURE / NFOGEN_COOKIE_SAMESITE

Routes :
    GET  /health
    GET  /profiles
    POST /generate, /generate/json, /propose-name         (proteges par require_token_for_generate)
    GET  /auth/status ; POST /login, /logout
    GET/POST/DELETE /accounts, /accounts/{username}
    GET/PUT/DELETE /profiles/store/{name} ; /export ; /import
"""
from __future__ import annotations

import csv
import hmac
import io
import json
import logging
import os
import secrets
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, NamedTuple, Optional

from fastapi import Cookie, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import accounts, engine, profile_store
from .accounts import AccountsError
from .profile_store import ProfileStoreError

# GapScan : extra optionnel (pip install nfogen[gapscan]), pas une
# dependance dure de l'API -- une install nfogen[api] seule (sans httpx)
# doit continuer a demarrer normalement, /gapscan/* renvoie alors 501.
try:
    from . import (
        commit_job_runner,
        gapscan,
        gapscan_config_store,
        gapscan_library,
        gapscan_runner,
        tracker_profile,
        upload_prep,
    )
    from .radarr_client import RadarrClient, RadarrError
    from .sonarr_client import SonarrClient, SonarrError
    from .torznab_client import TorznabClient, TorznabError

    _GAPSCAN_AVAILABLE = True
except ImportError:
    _GAPSCAN_AVAILABLE = False

logger = logging.getLogger("nfogen.api")

_LOG_LEVEL = os.environ.get("NFOGEN_LOG_LEVEL", "INFO").upper()
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=getattr(logging, _LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
logging.getLogger("nfogen").setLevel(getattr(logging, _LOG_LEVEL, logging.INFO))

_API_TOKEN = os.environ.get("NFOGEN_API_TOKEN")
_CORS_ORIGINS = [o.strip() for o in os.environ.get("NFOGEN_CORS_ORIGINS", "").split(",") if o.strip()]
_max_upload_mb = os.environ.get("NFOGEN_MAX_UPLOAD_MB")
_MAX_UPLOAD_BYTES = int(_max_upload_mb) * 1024 * 1024 if _max_upload_mb else None
_UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024
_REQUIRE_AUTH_FOR_GENERATE = os.environ.get("NFOGEN_REQUIRE_AUTH_FOR_GENERATE", "0") == "1"
_generate_rate_limit = os.environ.get("NFOGEN_GENERATE_RATE_LIMIT_PER_MINUTE")
_GENERATE_RATE_LIMIT_PER_MINUTE = int(_generate_rate_limit) if _generate_rate_limit else None
_GENERATE_RATE_WINDOW_SECONDS = 60.0
_TRUST_PROXY_HEADERS = os.environ.get("NFOGEN_TRUST_PROXY_HEADERS", "0") == "1"


class _Session(NamedTuple):
    """`identity` : compte nomme, ou None pour une connexion par token partage."""

    identity: Optional[str]
    created_at: float
    last_seen: float


_SESSIONS: dict[str, _Session] = {}
_SESSION_COOKIE_NAME = "nfogen_session"
_SESSION_IDLE_TIMEOUT_SECONDS = float(os.environ.get("NFOGEN_SESSION_IDLE_TIMEOUT_MINUTES", "1440")) * 60
_SESSION_MAX_LIFETIME_SECONDS = float(os.environ.get("NFOGEN_SESSION_MAX_LIFETIME_HOURS", "168")) * 3600


def _session_expired(session: _Session, now: float) -> bool:
    return (
        now - session.last_seen > _SESSION_IDLE_TIMEOUT_SECONDS
        or now - session.created_at > _SESSION_MAX_LIFETIME_SECONDS
    )


def _touch_session(session_cookie: Optional[str]) -> bool:
    """Vrai si la session existe et n'a pas expire ; rafraichit son activite."""
    if session_cookie is None:
        return False
    session = _SESSIONS.get(session_cookie)
    if session is None:
        return False
    now = time.monotonic()
    if _session_expired(session, now):
        del _SESSIONS[session_cookie]
        return False
    _SESSIONS[session_cookie] = session._replace(last_seen=now)
    return True


class _LoginAttempts(NamedTuple):
    failures: int
    locked_until: float
    last_attempt: float


_LOGIN_ATTEMPTS: dict[str, _LoginAttempts] = {}
_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_LOCKOUT_SECONDS = 30.0
_LOGIN_ATTEMPTS_TTL_SECONDS = 3600.0

_GENERATE_REQUEST_LOG: dict[str, list[float]] = {}

_SWEEP_INTERVAL_SECONDS = 300.0
_last_sweep = 0.0


def _sweep_stale_entries() -> None:
    """Purge sessions/tentatives/IP expirees, au plus une fois toutes les 5 min."""
    global _last_sweep
    now = time.monotonic()
    if now - _last_sweep < _SWEEP_INTERVAL_SECONDS:
        return
    _last_sweep = now
    for session_id, session in list(_SESSIONS.items()):
        if _session_expired(session, now):
            del _SESSIONS[session_id]
    for key, attempt in list(_LOGIN_ATTEMPTS.items()):
        if now - attempt.last_attempt > _LOGIN_ATTEMPTS_TTL_SECONDS:
            del _LOGIN_ATTEMPTS[key]
    for ip, timestamps in list(_GENERATE_REQUEST_LOG.items()):
        fresh = [t for t in timestamps if now - t <= _GENERATE_RATE_WINDOW_SECONDS]
        if fresh:
            _GENERATE_REQUEST_LOG[ip] = fresh
        else:
            del _GENERATE_REQUEST_LOG[ip]


_COOKIE_SECURE = os.environ.get("NFOGEN_COOKIE_SECURE", "0") == "1"
_COOKIE_SAMESITE = os.environ.get("NFOGEN_COOKIE_SAMESITE", "lax")


def _admin_auth_configured() -> bool:
    return _API_TOKEN is not None or accounts.is_configured()


def _accounts_bootstrap_available() -> bool:
    """Vrai si le tout premier compte peut etre cree sans authentification."""
    if _API_TOKEN is not None or not accounts.is_configured():
        return False
    try:
        return not accounts.list_accounts()
    except AccountsError:
        return False


_store_protected = _admin_auth_configured()
_generate_protected = _store_protected and _REQUIRE_AUTH_FOR_GENERATE
print(
    f"[nfogen] NFOGEN_API_TOKEN={'definie' if _API_TOKEN is not None else 'absente'} | "
    f"NFOGEN_ACCOUNTS_FILE={'definie' if accounts.is_configured() else 'absente'} | "
    f"NFOGEN_REQUIRE_AUTH_FOR_GENERATE={_REQUIRE_AUTH_FOR_GENERATE} -> "
    f"generation : {'protegee' if _generate_protected else 'ouverte a tous'} | "
    f"gestion de profils : {'protegee' if _store_protected else 'ouverte a tous'}",
    flush=True,
)

app = FastAPI(
    title="nfogen",
    version="0.1.0",
    description="Generation de fichiers NFO basee sur des profils.",
)

if _CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def _limit_upload_size(request: Request, call_next):
    """Rejette les requetes dont le Content-Length declare depasse le plafond."""
    if _MAX_UPLOAD_BYTES is not None:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_UPLOAD_BYTES:
            return PlainTextResponse(
                f"Corps de requete trop volumineux (max {_MAX_UPLOAD_BYTES // (1024 * 1024)} Mo).",
                status_code=413,
            )
    return await call_next(request)


def require_token(
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=_SESSION_COOKIE_NAME),
) -> None:
    """Protege une route via `Authorization: Bearer <token>` ou cookie de session."""
    _sweep_stale_entries()
    if not _admin_auth_configured():
        return
    if _API_TOKEN is not None and authorization is not None:
        prefix = "Bearer "
        if authorization.startswith(prefix):
            provided = authorization[len(prefix) :]
            if hmac.compare_digest(provided.encode("utf-8"), _API_TOKEN.encode("utf-8")):
                return
    if _touch_session(session_cookie):
        return
    raise HTTPException(status_code=401, detail="Authentification invalide ou manquante.")


def require_token_for_generate(
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=_SESSION_COOKIE_NAME),
) -> None:
    """Protege /generate*, seulement si NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1."""
    if not _REQUIRE_AUTH_FOR_GENERATE:
        return
    require_token(authorization=authorization, session_cookie=session_cookie)


def _client_ip(request: Request) -> str:
    """IP consideree comme celle du client, pour le rate-limit et le verrou
    anti-bruteforce du login. Par defaut, l'IP TCP directe -- suffisant tant
    que nfogen encaisse les connexions directement. Derriere un reverse
    proxy (Caddy ajoute par scripts/install.sh via NFOGEN_DOMAIN/
    NFOGEN_LOCAL_TLS), cette IP directe est TOUJOURS celle du proxy : sans
    NFOGEN_TRUST_PROXY_HEADERS=1, tous les clients partageraient un seul
    quota. Active, on lit X-Forwarded-For et on ne retient QUE la valeur la
    plus a droite -- celle ajoutee par notre reverse proxy immediat, jamais
    falsifiable par le client (qui peut pre-remplir l'en-tete lui-meme avant
    que le proxy n'y ajoute sa propre valeur). Ne PAS activer sans reverse
    proxy devant l'API : n'importe quel client pourrait alors usurper l'IP
    de son choix via cet en-tete."""
    direct_ip = request.client.host if request.client is not None else "unknown"
    if not _TRUST_PROXY_HEADERS:
        return direct_ip
    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return direct_ip
    return forwarded.rsplit(",", 1)[-1].strip() or direct_ip


def rate_limit_generate(request: Request) -> None:
    """Plafonne les requetes/minute par IP sur /generate*, si active."""
    if _GENERATE_RATE_LIMIT_PER_MINUTE is None:
        return
    _sweep_stale_entries()
    client_ip = _client_ip(request)
    now = time.monotonic()
    timestamps = _GENERATE_REQUEST_LOG.setdefault(client_ip, [])
    cutoff = now - _GENERATE_RATE_WINDOW_SECONDS
    while timestamps and timestamps[0] < cutoff:
        timestamps.pop(0)
    if len(timestamps) >= _GENERATE_RATE_LIMIT_PER_MINUTE:
        retry_after = max(1, int(_GENERATE_RATE_WINDOW_SECONDS - (now - timestamps[0])) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"Trop de requetes de generation depuis cette adresse (max "
            f"{_GENERATE_RATE_LIMIT_PER_MINUTE}/min).",
            headers={"Retry-After": str(retry_after)},
        )
    timestamps.append(now)


def _login_throttle_key(username: Optional[str], client_ip: str) -> str:
    """Compte nomme : verrou par identifiant (protege un compte cible, quelle
    que soit l'IP d'origine). Token partage (`username` absent) : un seul
    "compte" existe pour tout le monde, donc verrou par IP -- sinon un tiers
    anonyme pourrait bloquer le login par token pour tous les utilisateurs."""
    return f"user:{username}" if username else f"token:{client_ip}"


def _check_not_locked(key: str) -> None:
    attempt = _LOGIN_ATTEMPTS.get(key, _LoginAttempts(0, 0.0, 0.0))
    if attempt.locked_until > time.monotonic():
        raise HTTPException(status_code=429, detail="Trop de tentatives, reessayez plus tard.")


def _record_login_failure(key: str) -> None:
    attempt = _LOGIN_ATTEMPTS.get(key, _LoginAttempts(0, 0.0, 0.0))
    count = attempt.failures + 1
    now = time.monotonic()
    locked_until = now + _LOGIN_LOCKOUT_SECONDS if count >= _MAX_LOGIN_ATTEMPTS else 0.0
    _LOGIN_ATTEMPTS[key] = _LoginAttempts(count, locked_until, now)


def _record_login_success(key: str) -> None:
    _LOGIN_ATTEMPTS.pop(key, None)


class LoginRequest(BaseModel):
    token: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


@app.post("/login")
def login(req: LoginRequest, request: Request, response: Response) -> dict[str, str]:
    """Verifie le token ou un compte nomme, pose un cookie de session httpOnly."""
    _sweep_stale_entries()
    client_ip = _client_ip(request)
    identity: Optional[str]
    if req.username:
        key = _login_throttle_key(req.username, client_ip)
        _check_not_locked(key)
        if not accounts.is_configured():
            raise HTTPException(
                status_code=400, detail="Comptes nommes non configures (NFOGEN_ACCOUNTS_FILE absente)."
            )
        if not accounts.authenticate(req.username, req.password or ""):
            _record_login_failure(key)
            raise HTTPException(status_code=401, detail="Identifiant ou mot de passe invalide.")
        identity = req.username
    elif req.token is not None:
        key = _login_throttle_key(None, client_ip)
        _check_not_locked(key)
        if _API_TOKEN is None:
            raise HTTPException(
                status_code=400, detail="Authentification non configuree (NFOGEN_API_TOKEN absente)."
            )
        if not hmac.compare_digest(req.token.encode("utf-8"), _API_TOKEN.encode("utf-8")):
            _record_login_failure(key)
            raise HTTPException(status_code=401, detail="Token API invalide.")
        identity = None
    else:
        raise HTTPException(status_code=400, detail="Fournir 'token', ou 'username' et 'password'.")

    _record_login_success(key)
    session_id = secrets.token_urlsafe(32)
    now = time.monotonic()
    _SESSIONS[session_id] = _Session(identity=identity, created_at=now, last_seen=now)
    response.set_cookie(
        _SESSION_COOKIE_NAME,
        session_id,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite=_COOKIE_SAMESITE,
        path="/",
    )
    return {"status": "ok"}


@app.post("/logout")
def logout(
    response: Response,
    session_cookie: Optional[str] = Cookie(default=None, alias=_SESSION_COOKIE_NAME),
) -> dict[str, str]:
    if session_cookie is not None:
        _SESSIONS.pop(session_cookie, None)
    response.delete_cookie(_SESSION_COOKIE_NAME, path="/")
    return {"status": "ok"}


@app.get("/auth/status")
def auth_status(
    session_cookie: Optional[str] = Cookie(default=None, alias=_SESSION_COOKIE_NAME),
) -> dict[str, Any]:
    """Etat d'authentification (jamais de secret) : utilise par le frontend."""
    auth_required = _admin_auth_configured()
    return {
        "auth_required": auth_required,
        "authenticated": not auth_required or _touch_session(session_cookie),
        "token_login_enabled": _API_TOKEN is not None,
        "accounts_login_enabled": accounts.is_configured(),
        "accounts_bootstrap_available": _accounts_bootstrap_available(),
    }


def _run_accounts(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except AccountsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erreur inattendue pendant la gestion d'un compte")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.") from exc


@app.get("/accounts", dependencies=[Depends(require_token)])
def list_accounts_route() -> list[str]:
    return _run_accounts(accounts.list_accounts)


class AccountCreateRequest(BaseModel):
    username: str
    password: str


# Verrou anti-course sur l'amorcage du premier compte (deux POST /accounts
# concurrents ne doivent pas pouvoir tous deux passer le controle "aucun
# compte n'existe encore").
_ACCOUNTS_BOOTSTRAP_LOCK = threading.Lock()


@app.post("/accounts")
def create_account_route(
    req: AccountCreateRequest,
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=_SESSION_COOKIE_NAME),
) -> dict[str, str]:
    """Cree un compte ; ouvert sans authentification uniquement pour le tout premier."""
    with _ACCOUNTS_BOOTSTRAP_LOCK:
        bootstrap = _API_TOKEN is None and not _run_accounts(accounts.list_accounts)
        if not bootstrap:
            require_token(authorization=authorization, session_cookie=session_cookie)
        _run_accounts(accounts.create_account, req.username, req.password)
    return {"status": "ok"}


@app.delete("/accounts/{username}", dependencies=[Depends(require_token)])
def delete_account_route(username: str) -> dict[str, str]:
    """Supprime un compte et revoque immediatement ses sessions actives."""
    _run_accounts(accounts.delete_account, username)
    for session_id, session in list(_SESSIONS.items()):
        if session.identity == username:
            del _SESSIONS[session_id]
    return {"status": "ok"}


def _run_propose(**kwargs: Any) -> Any:
    try:
        return engine.propose_release_name(**kwargs)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erreur inattendue pendant la proposition de nom")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.") from exc


def _run_generate(**kwargs: Any) -> str:
    try:
        return engine.generate(**kwargs)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erreur inattendue pendant la generation du NFO")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.") from exc


def _run_store(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except ProfileStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erreur inattendue pendant la gestion d'un profil")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.") from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/profiles")
def profiles() -> dict[str, list[str]]:
    return engine.list_available()


class JsonRequest(BaseModel):
    category: str
    profile: str = "c411"
    data: dict[str, Any] = {}
    options: dict[str, Any] = {}


def _header_safe(value: str) -> str:
    """Retire caracteres de controle/guillemets/antislash avant usage dans un en-tete HTTP."""
    return "".join(c for c in value if ord(c) >= 0x20 and c != "\x7f" and c not in '"\\')


def _filename(category: str, data: dict, declared_by_profile: str | None) -> str:
    if declared_by_profile:
        name = declared_by_profile
    else:
        base = data.get("title") or data.get("album") or category
        safe = "".join(c if c.isalnum() or c in "-._ " else "_" for c in str(base)).strip()
        name = f"{safe or category}.nfo"
    return _header_safe(name)


@app.post("/generate/json", dependencies=[Depends(require_token_for_generate), Depends(rate_limit_generate)])
def generate_json(req: JsonRequest, download: bool = Query(False)) -> Any:
    warnings: list[str] = []
    filename: list[str] = []
    nfo = _run_generate(
        category=req.category,
        profile=req.profile,
        data=req.data,
        options=req.options,
        warnings=warnings,
        filename=filename,
    )
    headers = {}
    if warnings:
        headers["X-Nfogen-Warnings"] = " | ".join(warnings)
    if download:
        name = _filename(req.category, req.data, filename[0] if filename else None)
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return PlainTextResponse(nfo, headers=headers)


class NameProposalRequest(BaseModel):
    category: str
    profile: str = "c411"
    filenames: list[str] = []
    title_hints: Optional[list[Optional[str]]] = None


@app.post("/propose-name", dependencies=[Depends(require_token_for_generate), Depends(rate_limit_generate)])
def propose_name(req: NameProposalRequest) -> dict[str, Any]:
    proposal = _run_propose(
        category=req.category,
        profile=req.profile,
        filenames=req.filenames,
        title_hints=req.title_hints,
    )
    return {"name": proposal.name, "fields": proposal.fields, "warnings": proposal.warnings}


@app.post("/generate", dependencies=[Depends(require_token_for_generate), Depends(rate_limit_generate)])
async def generate_upload(
    category: Optional[str] = Form(None),
    profile: str = Form("c411"),
    data: str = Form("{}"),
    options: str = Form("{}"),
    files: list[UploadFile] = File(default_factory=list),
    download: bool = Query(False),
) -> Any:
    try:
        extra = json.loads(data or "{}")
        opts = json.loads(options or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"JSON invalide : {exc}") from exc

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        saved: list[Path] = []
        total_written = 0
        for index, up in enumerate(files):
            # Path("..").name == ".." (pas ""), donc un fichier uploade nomme
            # ".." ecrirait dans le parent du dossier temporaire sans ce garde-fou.
            candidate_name = Path(up.filename or "").name
            if not candidate_name or candidate_name in (".", ".."):
                candidate_name = f"upload_{index}.bin"
            dest = tmp_path / candidate_name
            with dest.open("wb") as out:
                while chunk := await up.read(_UPLOAD_CHUNK_BYTES):
                    total_written += len(chunk)
                    if _MAX_UPLOAD_BYTES is not None and total_written > _MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"Corps de requete trop volumineux "
                            f"(max {_MAX_UPLOAD_BYTES // (1024 * 1024)} Mo).",
                        )
                    out.write(chunk)
            saved.append(dest)

        source = None if not saved else (saved[0] if len(saved) == 1 else tmp_path)

        warnings: list[str] = []
        filename: list[str] = []
        nfo = _run_generate(
            category=category,
            profile=profile,
            source=source,
            data=extra,
            options=opts,
            warnings=warnings,
            filename=filename,
        )

    headers = {}
    if warnings:
        headers["X-Nfogen-Warnings"] = " | ".join(warnings)
    if download:
        name = _filename(category or "release", extra, filename[0] if filename else None)
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return PlainTextResponse(nfo, headers=headers)


class ProfileWriteRequest(BaseModel):
    rules: dict[str, Any] = {}
    templates: dict[str, str] = {}


@app.get("/profiles/store", dependencies=[Depends(require_token)])
def list_managed_profiles() -> list[str]:
    return _run_store(profile_store.list_profiles)


@app.get("/profiles/store/{name}", dependencies=[Depends(require_token)])
def read_managed_profile(name: str) -> dict[str, Any]:
    return _run_store(profile_store.read_profile, name)


@app.put("/profiles/store/{name}", dependencies=[Depends(require_token)])
def write_managed_profile(name: str, req: ProfileWriteRequest) -> dict[str, str]:
    _run_store(profile_store.write_profile, name, rules=req.rules, templates=req.templates)
    return {"status": "ok", "name": name}


@app.delete("/profiles/store/{name}", dependencies=[Depends(require_token)])
def delete_managed_profile(name: str) -> dict[str, str]:
    _run_store(profile_store.delete_profile, name)
    return {"status": "ok", "name": name}


@app.get("/profiles/store/{name}/export", dependencies=[Depends(require_token)])
def export_managed_profile(name: str) -> Response:
    content = _run_store(profile_store.export_profile_zip, name)
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


@app.post("/profiles/store/{name}/import", dependencies=[Depends(require_token)])
async def import_managed_profile(name: str, file: UploadFile = File(...)) -> dict[str, str]:
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(_UPLOAD_CHUNK_BYTES):
        total += len(chunk)
        if _MAX_UPLOAD_BYTES is not None and total > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Archive trop volumineuse (max {_MAX_UPLOAD_BYTES // (1024 * 1024)} Mo).",
            )
        chunks.append(chunk)
    content = b"".join(chunks)
    _run_store(profile_store.import_profile_zip, name, content)
    return {"status": "ok", "name": name}


# --------------------------------------------------------------------------- #
# GapScan (voir GAPSCAN.md) : compare la bibliotheque locale (Sonarr/Radarr)
# au catalogue C411 pour identifier des candidats a l'upload. Protege comme
# /profiles/store* (meme modele -- require_token). Configuration
# (URLs + cles Sonarr/Radarr/C411) geree par gapscan_config_store.py :
# fichier optionnel (NFOGEN_GAPSCAN_CONFIG_FILE, modifiable a chaud via
# PUT /gapscan/config), repli sur les variables d'environnement historiques
# sinon. Contrairement a NFOGEN_API_TOKEN (jamais de PUT, boot-time
# uniquement), ce sont des identifiants SORTANTS vers des services tiers :
# l'admin doit pouvoir les changer sans redemarrer nfogen. Un seul scan a
# la fois (gapscan_runner.py), execute en tache de fond (peut prendre
# plusieurs minutes sur une grosse bibliotheque).
# --------------------------------------------------------------------------- #
def _require_gapscan_available() -> None:
    if not _GAPSCAN_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail="GapScan necessite l'extra optionnel : pip install nfogen[gapscan]",
        )


@app.get("/gapscan/config", dependencies=[Depends(require_token)])
def gapscan_config(profile: str = Query("c411")) -> dict[str, Any]:
    """Jamais les cles elles-memes, seulement si chaque service est
    configure (+ son URL, non sensible) -- meme principe que /auth/status
    pour NFOGEN_API_TOKEN."""
    _require_gapscan_available()
    return gapscan_config_store.status(profile)


class GapscanConfigWriteRequest(BaseModel):
    profile: str = "c411"
    tracker_api_key: Optional[str] = None
    tracker_base_url: Optional[str] = None
    tracker_announce_url: Optional[str] = None
    sonarr_url: Optional[str] = None
    sonarr_api_key: Optional[str] = None
    radarr_url: Optional[str] = None
    radarr_api_key: Optional[str] = None
    sonarr_path_mappings: Optional[dict[str, str]] = None
    radarr_path_mappings: Optional[dict[str, str]] = None
    staging_dir: Optional[str] = None


@app.put("/gapscan/config", dependencies=[Depends(require_token)])
def gapscan_config_write(req: GapscanConfigWriteRequest) -> dict[str, Any]:
    """Met a jour uniquement les champs fournis (les autres restent
    inchanges) -- voir gapscan_config_store.write()."""
    _require_gapscan_available()
    fields = req.model_dump()
    profile = fields.pop("profile")
    try:
        gapscan_config_store.write(profile=profile, **fields)
    except gapscan_config_store.GapscanConfigStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return gapscan_config_store.status(profile)


def _min_request_interval(profile: str) -> float:
    """Delai minimal entre deux requetes -- source de verite : le profil
    (rules.json -> tracker.min_request_interval_seconds, voir
    tracker_profile.py). L'ancienne variable d'environnement reste lisible
    comme un simple override de deploiement, UNIQUEMENT pour le profil
    c411 (c'est le seul qui existait quand cette variable a ete introduite
    -- voir AUTOMATION.md, sous-projet 4b)."""
    default = tracker_profile.min_request_interval_seconds(profile)
    if profile == "c411":
        return float(os.environ.get("NFOGEN_C411_MIN_INTERVAL_SECONDS", str(default)))
    return default


def _build_gapscan_clients(profile: str) -> tuple[Any, Any, Any, dict[str, str], dict[str, str]]:
    """Construit les clients GapScan pour CE profil depuis
    gapscan_config_store (fichier ou environnement), plus les mappings de
    chemins configures (globaux, pas par profil). Leve ValueError (-> 400)
    si la configuration necessaire manque."""
    tracker_config = gapscan_config_store.effective_tracker(profile)
    if tracker_config is None:
        raise ValueError(
            f"Clé API du tracker '{profile}' non configurée "
            "(NFOGEN_C411_API_KEY si profile=c411, ou PUT /gapscan/config) : voir GAPSCAN.md."
        )
    tracker_key, tracker_base_url = tracker_config
    min_interval = _min_request_interval(profile)
    tracker_client = TorznabClient(
        tracker_key, base_url=tracker_base_url.rstrip("/") + "/api", min_interval_seconds=min_interval
    )

    sonarr_config = gapscan_config_store.effective_sonarr()
    sonarr = SonarrClient(*sonarr_config) if sonarr_config else None

    radarr_config = gapscan_config_store.effective_radarr()
    radarr = RadarrClient(*radarr_config) if radarr_config else None

    if sonarr is None and radarr is None:
        tracker_client.close()
        raise ValueError(
            "Aucune instance Sonarr ni Radarr configuree "
            "(NFOGEN_SONARR_URL/_API_KEY et/ou NFOGEN_RADARR_URL/_API_KEY, ou PUT /gapscan/config)."
        )
    return (
        tracker_client, sonarr, radarr,
        gapscan_config_store.effective_sonarr_path_mappings(),
        gapscan_config_store.effective_radarr_path_mappings(),
    )


class GapscanRunRequest(BaseModel):
    # Cles serialisees en JSON (voir gapscan.movie_key/series_key,
    # upload_history_store.key_str) -- transport opaque, decodees ci-dessous.
    selection: Optional[list[str]] = None


@app.post("/gapscan/run", dependencies=[Depends(require_token)])
def gapscan_run(
    incremental: bool = Query(False),
    only: Optional[str] = Query(None),
    profile: str = Query("c411"),
    req: GapscanRunRequest = GapscanRunRequest(),
) -> dict[str, str]:
    """`incremental=true` : reutilise les resultats du dernier scan pour les
    titres deja couverts et inchanges localement (au-dela de
    NFOGEN_GAPSCAN_INCREMENTAL_MAX_AGE_DAYS, reverifie quand meme -- C411
    retire/ajoute des torrents assez souvent). `only=movies`/`only=series` :
    ne scanne qu'une des deux bibliotheques, pour repartir la charge sur
    plusieurs sessions (limite C411 confirmee : 15 requetes/min). `profile` :
    quel tracker interroger (identifiants/reglages namespaces, voir
    gapscan_config_store.py/tracker_profile.py). `req.selection`
    (AUTOMATION.md, sous-projet 8, optionnel) : cles serialisees en JSON
    (voir gapscan.movie_key/series_key) -- decodees ici puis transmises
    telles quelles a gapscan_runner.start(). A priorite sur `only` (gere par
    run_gapscan lui-meme). Une cle mal formee (JSON invalide) -> 400 ; une
    cle bien formee mais ne correspondant a aucun item reel est simplement
    ignoree plus loin (jamais une erreur). Voir gapscan_runner.start()."""
    _require_gapscan_available()
    if only not in (None, "movies", "series"):
        raise HTTPException(status_code=400, detail="only doit valoir 'movies' ou 'series'.")
    selection: Optional[set[tuple]] = None
    if req.selection:
        try:
            selection = {tuple(json.loads(k)) for k in req.selection}
        except (json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(status_code=400, detail=f"Clé de sélection invalide : {exc}") from exc
    try:
        tracker_client, sonarr, radarr, sonarr_path_mappings, radarr_path_mappings = (
            _build_gapscan_clients(profile)
        )
    except (ValueError, TorznabError, SonarrError, RadarrError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Bug reel trouve en audit (2026-08-27) : "au moins Sonarr OU Radarr
    # configure" (verifie par _build_gapscan_clients) ne suffit pas quand
    # `only` cible precisement celui qui MANQUE -- sans ce garde-fou, le
    # scan "reussissait" en silence avec 0 titre traite.
    if only == "movies" and radarr is None:
        tracker_client.close()
        if sonarr is not None:
            sonarr.close()
        raise HTTPException(
            status_code=400,
            detail="only=movies demande, mais Radarr n'est pas configure.",
        )
    if only == "series" and sonarr is None:
        tracker_client.close()
        if radarr is not None:
            radarr.close()
        raise HTTPException(
            status_code=400,
            detail="only=series demande, mais Sonarr n'est pas configure.",
        )

    max_age_days = float(os.environ.get("NFOGEN_GAPSCAN_INCREMENTAL_MAX_AGE_DAYS", "7"))
    max_age_seconds = max_age_days * 86400 if incremental else None
    started = gapscan_runner.start(
        tracker_client, radarr=radarr, sonarr=sonarr, incremental=incremental,
        only=only, max_age_seconds=max_age_seconds,
        sonarr_path_mappings=sonarr_path_mappings, radarr_path_mappings=radarr_path_mappings,
        selection=selection,
    )
    if not started:
        tracker_client.close()
        if sonarr is not None:
            sonarr.close()
        if radarr is not None:
            radarr.close()
        raise HTTPException(status_code=409, detail="Un scan GapScan est deja en cours.")
    return {"status": "started"}


@app.get("/gapscan/status", dependencies=[Depends(require_token)])
def gapscan_status() -> dict[str, Any]:
    _require_gapscan_available()
    return gapscan_runner.status()


@app.get("/gapscan/results", dependencies=[Depends(require_token)])
def gapscan_results(
    status: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    profile: str = Query("c411"),
) -> dict[str, Any]:
    _require_gapscan_available()
    items = gapscan_runner.results(
        status_filter=status, media_type_filter=media_type, genre_filter=genre, profile=profile
    )
    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    serialized: list[dict[str, Any]] = []
    for r in page_items:
        d = asdict(r)
        d["genre"] = gapscan.genre_of(r, profile)
        serialized.append(d)
    return {"items": serialized, "total": total}


_CSV_COLUMNS = [
    "media_type", "title", "year", "season_number", "status", "genre",
    "imdb_id", "tmdb_id", "tvdb_id",
    "local_resolution", "local_source", "local_languages",
    "has_freeleech_alternative", "has_double_upload_window", "error",
]


@app.get("/gapscan/results/export.csv", dependencies=[Depends(require_token)])
def gapscan_results_export_csv(
    status: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    profile: str = Query("c411"),
) -> Response:
    _require_gapscan_available()
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_CSV_COLUMNS)
    for r in gapscan_runner.results(
        status_filter=status, media_type_filter=media_type, genre_filter=genre, profile=profile
    ):
        writer.writerow(
            [
                r.media_type, r.title, r.year, r.season_number, r.status.value,
                gapscan.genre_of(r, profile) or "",
                r.imdb_id, r.tmdb_id, r.tvdb_id,
                r.local_quality.resolution, r.local_quality.source,
                "+".join(r.local_quality.languages),
                r.has_freeleech_alternative, r.has_double_upload_window, r.error or "",
            ]
        )
    return Response(
        buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="gapscan.csv"'},
    )


@app.get("/gapscan/library", dependencies=[Depends(require_token)])
def gapscan_library_endpoint(
    q: Optional[str] = Query(None),
    media_type: Optional[str] = Query(None),
    genre: Optional[str] = Query(None),
    added_since_days: Optional[float] = Query(None),
    processed: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Inventaire local Radarr/Sonarr, ZERO appel tracker (AUTOMATION.md,
    sous-projet 8) -- rechargement quasi instantane, contrairement a
    POST /gapscan/run. `q` : recherche texte sur le titre (insensible a la
    casse, sous-chaine). `added_since_days` : ne garde que les items
    ajoutes il y a moins de N jours (ignore les items sans added_at
    connu). `processed` : filtre sur already_processed."""
    _require_gapscan_available()
    sonarr_config = gapscan_config_store.effective_sonarr()
    sonarr = SonarrClient(*sonarr_config) if sonarr_config else None
    radarr_config = gapscan_config_store.effective_radarr()
    radarr = RadarrClient(*radarr_config) if radarr_config else None
    if sonarr is None and radarr is None:
        raise HTTPException(
            status_code=400,
            detail="Aucune instance Sonarr ni Radarr configuree "
            "(NFOGEN_SONARR_URL/_API_KEY et/ou NFOGEN_RADARR_URL/_API_KEY, ou PUT /gapscan/config).",
        )
    try:
        items = gapscan_library.list_library(radarr=radarr, sonarr=sonarr)
    except (RadarrError, SonarrError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if sonarr is not None:
            sonarr.close()
        if radarr is not None:
            radarr.close()

    if q:
        needle = q.strip().lower()
        items = [i for i in items if needle in i.title.lower()]
    if media_type is not None:
        items = [i for i in items if i.media_type == media_type]
    if genre is not None:
        items = [i for i in items if genre in i.genres]
    if added_since_days is not None:
        cutoff = time.time() - added_since_days * 86400
        items = [i for i in items if i.added_at is not None and i.added_at >= cutoff]
    if processed is not None:
        items = [i for i in items if i.already_processed == processed]

    total = len(items)
    start = (page - 1) * page_size
    page_items = items[start : start + page_size]
    return {"items": [asdict(i) for i in page_items], "total": total}


# --------------------------------------------------------------------------- #
# Preparation d'upload (AUTOMATION.md, sous-projet 4) : nommage -> mise en
# scene + .torrent, a partir de chemins locaux deja resolus (voir
# GapResult.local_paths, sous-projet 1). Le frontend a deja ces chemins en
# memoire depuis GET /gapscan/results -- pas besoin d'un identifiant
# GapResult, ce module reste decouple du modele de donnees GapScan.
# --------------------------------------------------------------------------- #
def _run_upload_prep(fn: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erreur inattendue pendant la préparation d'upload")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.") from exc


class PrepareUploadPreviewRequest(BaseModel):
    local_paths: list[str] = []
    profile: str = "c411"
    title_override: Optional[str] = None


@app.post("/gapscan/prepare-upload/preview", dependencies=[Depends(require_token)])
def gapscan_prepare_upload_preview(req: PrepareUploadPreviewRequest) -> list[dict[str, Any]]:
    _require_gapscan_available()
    proposals = _run_upload_prep(
        upload_prep.preview_upload, req.local_paths, profile=req.profile, title_override=req.title_override
    )
    return [asdict(p) for p in proposals]


class PrepareUploadFile(BaseModel):
    source_path: str
    staged_name: str


class PrepareUploadCommitRequest(BaseModel):
    release_name: str
    files: list[PrepareUploadFile]
    profile: str = "c411"


@app.post("/gapscan/prepare-upload/commit", dependencies=[Depends(require_token)])
def gapscan_prepare_upload_commit(req: PrepareUploadCommitRequest) -> dict[str, str]:
    """Demarre la mise en scene + generation de .torrent EN TACHE DE FOND
    (AUTOMATION.md, sous-projet 4c) -- renvoie un job_id immediatement,
    suivi via GET /gapscan/commit-jobs/{job_id}. Erreurs de configuration
    (staging_dir/announce_url manquants) restent surfacees immediatement
    (voir upload_prep.resolve_staging_config, verifie AVANT de demarrer la
    tache, dans commit_job_runner.start())."""
    _require_gapscan_available()
    files = [
        upload_prep.ProposedFile(source_path=f.source_path, staged_name=f.staged_name) for f in req.files
    ]
    job_id = _run_upload_prep(commit_job_runner.start, req.release_name, files, profile=req.profile)
    return {"job_id": job_id}


@app.get("/gapscan/commit-jobs", dependencies=[Depends(require_token)])
def gapscan_commit_jobs() -> list[dict[str, Any]]:
    _require_gapscan_available()
    return commit_job_runner.list_jobs()


@app.get("/gapscan/commit-jobs/{job_id}", dependencies=[Depends(require_token)])
def gapscan_commit_job_status(job_id: str) -> dict[str, Any]:
    _require_gapscan_available()
    status = commit_job_runner.status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Tâche inconnue.")
    return status


@app.post("/gapscan/commit-jobs/{job_id}/cancel", dependencies=[Depends(require_token)])
def gapscan_commit_job_cancel(job_id: str) -> dict[str, str]:
    _require_gapscan_available()
    status = commit_job_runner.status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Tâche inconnue.")
    if status["state"] in ("done", "error", "cancelled"):
        raise HTTPException(status_code=409, detail="Cette tâche est déjà terminée.")
    commit_job_runner.cancel(job_id)
    return {"status": "cancelling"}


class PrepareUploadSendRequest(BaseModel):
    release_name: str
    staged_path: str
    torrent_path: str
    nfo_path: str
    profile: str = "c411"
    media_type: str = "movie"
    radarr_movie_id: Optional[int] = None
    sonarr_series_id: Optional[int] = None
    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    genre: Optional[str] = None
    season_number: Optional[int] = None
    draft_id: Optional[Any] = None


@app.post("/gapscan/prepare-upload/send", dependencies=[Depends(require_token)])
def gapscan_prepare_upload_send(req: PrepareUploadSendRequest) -> dict[str, Any]:
    """Cree (ou met a jour) un BROUILLON C411 -- jamais une soumission
    reelle en moderation (voir AUTOMATION.md, sous-projet 5, decision 6)."""
    _require_gapscan_available()
    result = _run_upload_prep(
        upload_prep.send_to_tracker,
        release_name=req.release_name, staged_path=req.staged_path, torrent_path=req.torrent_path,
        nfo_path=req.nfo_path, profile=req.profile, media_type=req.media_type,
        radarr_movie_id=req.radarr_movie_id, sonarr_series_id=req.sonarr_series_id,
        tmdb_id=req.tmdb_id, tvdb_id=req.tvdb_id, genre=req.genre, season_number=req.season_number,
        draft_id=req.draft_id,
    )
    return asdict(result)


# Frontend builde, optionnel (NFOGEN_FRONTEND_DIST) : enregistre en dernier,
# les routes API ci-dessus restent prioritaires.
_frontend_dist = os.environ.get("NFOGEN_FRONTEND_DIST")
if _frontend_dist:
    _FRONTEND_DIR = Path(_frontend_dist).resolve()
    if not (_FRONTEND_DIR / "index.html").is_file():
        raise RuntimeError(
            f"NFOGEN_FRONTEND_DIST='{_frontend_dist}' ne contient pas index.html "
            "(build attendu : `cd frontend && npm run build` -> frontend/dist)."
        )
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIR / "assets"), name="frontend-assets")

    _FRONTEND_DIR_REAL = os.path.realpath(_FRONTEND_DIR) + os.sep

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str) -> FileResponse:
        """Sert un fichier statique reel, sinon index.html (SPA, React Router)."""
        candidate = os.path.realpath(os.path.join(str(_FRONTEND_DIR), full_path))
        if full_path and candidate.startswith(_FRONTEND_DIR_REAL) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIR / "index.html")
