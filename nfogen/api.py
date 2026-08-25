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

import hmac
import json
import logging
import os
import secrets
import tempfile
import threading
import time
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
