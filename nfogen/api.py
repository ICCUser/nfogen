"""Service HTTP (FastAPI) pour la generation automatisee de NFO.

Lancer :
    uvicorn nfogen.api:app --host 0.0.0.0 --port 8000

Deux usages :
1) Envoi de fichier(s)  -> POST /generate (multipart)
   - le service extrait les metadonnees et renvoie le NFO.
2) Envoi de metadonnees -> POST /generate/json (application/json)
   - aucun fichier requis ; utile pour jeux/ebook/3d ou pour la video si le
     client a deja extrait le texte MediaInfo (champ data.raw_text).

Pour la video, l'option (2) avec data.raw_text evite d'uploader plusieurs Go :
le client fait `mediainfo film.mkv` localement et poste le texte.

POST /propose-name (JSON, sans upload) suggere un `release_name` a partir des
seuls NOMS de fichiers (pas leur contenu) pour les profils qui declarent un
`name_proposal` dans leur rules.json (categorie video) : utile pour pre-
remplir le champ avant generation, dans un script ou dans le frontend.

Configuration (variables d'environnement, toutes optionnelles) :
    NFOGEN_API_TOKEN      Si definie, exige soit l'en-tete `Authorization:
                           Bearer <token>` (CLI/scripts), soit le cookie de
                           session pose par POST /login (frontend web), pour
                           les routes /profiles/store* (gestion de profils,
                           toujours protegees si la variable est definie).
                           N'affecte PAS /generate, /generate/json et
                           /propose-name par defaut (cf.
                           NFOGEN_REQUIRE_AUTH_FOR_GENERATE) : generation
                           ouverte a tous et gestion de profils reservee a
                           qui a le token sont deux niveaux distincts. Si la
                           variable est absente, tout reste ouvert.
    NFOGEN_REQUIRE_AUTH_FOR_GENERATE
                           "1" pour exiger aussi le token (meme mecanisme que
                           ci-dessus) sur /generate, /generate/json et
                           /propose-name. Inactif par defaut : ces routes
                           restent ouvertes a tous via le web meme quand
                           NFOGEN_API_TOKEN protege la gestion de profils.
                           A activer si l'API est exposee publiquement et que
                           l'operateur craint l'abus (uploads volumineux).
    NFOGEN_CORS_ORIGINS   Liste d'origines autorisees, separees par des
                           virgules (ex. "http://localhost:5173"). Si absente,
                           aucun CORS n'est active (pas d'appel cross-origin).
    NFOGEN_MAX_UPLOAD_MB  Taille maximale acceptee pour /generate, en Mo.
                           Par defaut illimitee (variable absente) : les
                           fichiers sources (video, jeux, scans...) peuvent
                           legitimement peser plusieurs centaines de Go.
                           Definir une valeur pour appliquer un plafond
                           (utile si l'API est exposee publiquement).
    NFOGEN_PROFILES_DIR   Dossier de profils utilisateur, gerable via les
                           routes `/profiles/store*` (lister/lire/creer/
                           editer/supprimer/exporter/importer). Sans elle,
                           ces routes renvoient une erreur 400 explicite.
    NFOGEN_FRONTEND_DIST  Dossier du build frontend (`frontend/npm run
                           build` -> `frontend/dist`). Si definie, l'API sert
                           aussi le frontend (fichiers statiques + repli sur
                           `index.html` pour les routes React Router) sur le
                           MEME processus/port : pratique pour un deploiement
                           "tout-en-un" (installation native ou image Docker)
                           sans nginx ni service separe. Absente par defaut :
                           l'API reste API-only (comportement historique, ex.
                           dev avec `vite dev` separe).

    POST   /propose-name          suggestion de release_name (noms de fichiers seuls)

Gestion de profils utilisateur (toutes les routes `/profiles/store*` exigent
le token API comme `/generate` ; voir `nfogen/profile_store.py`) :
    GET    /profiles/store               liste des profils utilisateur
    GET    /profiles/store/{name}        regles + templates d'un profil
    PUT    /profiles/store/{name}        cree/remplace un profil
    DELETE /profiles/store/{name}        supprime un profil
    GET    /profiles/store/{name}/export archive .zip du profil
    POST   /profiles/store/{name}/import depose un .zip (cree/remplace)
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import Cookie, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import engine, profile_store
from .profile_store import ProfileStoreError

logger = logging.getLogger("nfogen.api")

_API_TOKEN = os.environ.get("NFOGEN_API_TOKEN")
_CORS_ORIGINS = [o.strip() for o in os.environ.get("NFOGEN_CORS_ORIGINS", "").split(",") if o.strip()]
_max_upload_mb = os.environ.get("NFOGEN_MAX_UPLOAD_MB")
_MAX_UPLOAD_BYTES = int(_max_upload_mb) * 1024 * 1024 if _max_upload_mb else None
_UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024
# Par defaut, /generate, /generate/json et /propose-name restent ouverts a
# tous MEME quand NFOGEN_API_TOKEN protege /profiles/store* (cf.
# require_token_for_generate ci-dessous) : a "1" pour reactiver
# l'authentification sur la generation aussi.
_REQUIRE_AUTH_FOR_GENERATE = os.environ.get("NFOGEN_REQUIRE_AUTH_FOR_GENERATE", "0") == "1"

# Authentification par cookie de session (en plus de l'en-tete Authorization,
# cf. require_token ci-dessous) : le frontend web pose le token via POST
# /login puis ne le manipule plus jamais lui-meme -- le navigateur stocke le
# cookie, jamais lisible par du JavaScript (httponly=True), contrairement a
# l'ancien stockage en localStorage (alerte CodeQL "Clear text storage of
# sensitive information", cf. ROADMAP.md). L'en-tete Authorization reste
# disponible pour les clients non-navigateur (CLI, scripts, curl).
_SESSION_COOKIE_NAME = "nfogen_session"
# Secure (cookie envoye uniquement en HTTPS) desactive par defaut : l'install
# native documentee (scripts/install.sh) sert l'API en HTTP brut sur le
# reseau local par defaut (pas de TLS termine par nfogen lui-meme). A activer
# explicitement (NFOGEN_COOKIE_SECURE=1) derriere un reverse-proxy TLS.
_COOKIE_SECURE = os.environ.get("NFOGEN_COOKIE_SECURE", "0") == "1"
# SameSite=lax convient au deploiement documente (frontend et API sur la
# meme origine, directement ou via le proxy de dev/un reverse-proxy) ; un
# frontend heberge sur un AUTRE domaine que l'API doit passer a "none" (et
# alors NFOGEN_COOKIE_SECURE=1 est obligatoire, les navigateurs rejettent
# SameSite=None sans Secure).
_COOKIE_SAMESITE = os.environ.get("NFOGEN_COOKIE_SAMESITE", "lax")

# Affiche au demarrage la configuration d'authentification REELLEMENT
# appliquee : source frequente de confusion sinon (une variable
# d'environnement definie dans un terminal precedent et oubliee, par exemple,
# peut rester active apres un redemarrage du processus dans le MEME
# terminal). print() plutot que logger : doit etre visible quelle que soit
# la configuration de logging. flush=True : stdout est bufferise par bloc
# (pas par ligne) des qu'il n'est pas un terminal -- sortie redirigee vers un
# fichier, un service systemd, Docker... sans ca, cette ligne resterait
# invisible en pratique, exactement dans les cas ou elle est le plus utile.
_generate_protected = _API_TOKEN is not None and _REQUIRE_AUTH_FOR_GENERATE
_store_protected = _API_TOKEN is not None
print(
    f"[nfogen] NFOGEN_API_TOKEN={'definie' if _API_TOKEN is not None else 'absente'} | "
    f"NFOGEN_REQUIRE_AUTH_FOR_GENERATE={_REQUIRE_AUTH_FOR_GENERATE} -> "
    f"generation (/generate, /generate/json, /propose-name) : "
    f"{'protegee par token' if _generate_protected else 'ouverte a tous'} | "
    f"gestion de profils (/profiles/store*) : "
    f"{'protegee par token' if _store_protected else 'ouverte a tous'}",
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
        # Necessaire pour que le navigateur envoie/accepte le cookie de
        # session sur des requetes cross-origin (frontend et API sur des
        # domaines differents) ; sans danger ici car `allow_origins` est
        # toujours une liste explicite (jamais "*", incompatible avec les
        # credentials par les navigateurs eux-memes).
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def _limit_upload_size(request: Request, call_next):
    """Rejette tot les requetes dont le Content-Length annonce un corps trop
    volumineux. Inactif par defaut (`_MAX_UPLOAD_BYTES is None`, taille
    illimitee) ; protection simple contre l'abus si l'operateur definit
    `NFOGEN_MAX_UPLOAD_MB` (pas un garde-fou absolu : un client malhonnete
    pourrait mentir sur Content-Length)."""
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
    """Protege une route par token si `NFOGEN_API_TOKEN` est definie.

    Accepte soit l'en-tete `Authorization: Bearer <token>` (clients non-
    navigateur : CLI, scripts, curl), soit le cookie de session pose par
    `POST /login` (frontend web -- jamais manipule directement en
    JavaScript, cf. `_SESSION_COOKIE_NAME`). Sans `NFOGEN_API_TOKEN`, l'API
    reste ouverte : c'est un choix explicite de l'operateur d'activer
    l'authentification, pas un comportement force.
    """
    if _API_TOKEN is None:
        return
    if authorization == f"Bearer {_API_TOKEN}":
        return
    if session_cookie == _API_TOKEN:
        return
    raise HTTPException(status_code=401, detail="Token API invalide ou manquant.")


def require_token_for_generate(
    authorization: Optional[str] = Header(default=None),
    session_cookie: Optional[str] = Cookie(default=None, alias=_SESSION_COOKIE_NAME),
) -> None:
    """Protege `/generate`, `/generate/json` et `/propose-name` -- separement
    de `/profiles/store*`, toujours protegees par `require_token` seul.

    Par defaut, la generation de NFO reste ouverte a tous via le web MEME
    quand `NFOGEN_API_TOKEN` est definie pour proteger la gestion des profils
    (cf. ROADMAP.md, "Droits d'acces multi-utilisateurs") : un token unique
    ne doit pas forcer a choisir entre "tout ouvert" et "tout ferme".
    Definir `NFOGEN_REQUIRE_AUTH_FOR_GENERATE=1` reactive l'ancien
    comportement (utile si un operateur craint l'abus -- uploads volumineux,
    saturation disque -- sur un serveur expose publiquement)."""
    if not _REQUIRE_AUTH_FOR_GENERATE:
        return
    require_token(authorization=authorization, session_cookie=session_cookie)


class LoginRequest(BaseModel):
    token: str


@app.post("/login")
def login(req: LoginRequest, response: Response) -> dict[str, str]:
    """Verifie le token API et pose le cookie de session httpOnly (jamais
    lisible par du JavaScript, contrairement a l'ancien stockage en
    localStorage cote frontend)."""
    if _API_TOKEN is None:
        raise HTTPException(
            status_code=400, detail="Authentification non configuree (NFOGEN_API_TOKEN absente)."
        )
    if req.token != _API_TOKEN:
        raise HTTPException(status_code=401, detail="Token API invalide.")
    response.set_cookie(
        _SESSION_COOKIE_NAME,
        req.token,
        httponly=True,
        secure=_COOKIE_SECURE,
        samesite=_COOKIE_SAMESITE,
        path="/",
        # Pas de max_age/expires : cookie de session, efface a la fermeture
        # du navigateur (jamais persistant sur disque comme localStorage).
    )
    return {"status": "ok"}


@app.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(_SESSION_COOKIE_NAME, path="/")
    return {"status": "ok"}


@app.get("/auth/status")
def auth_status(
    session_cookie: Optional[str] = Cookie(default=None, alias=_SESSION_COOKIE_NAME),
) -> dict[str, bool]:
    """Etat d'authentification, sans exiger le token : permet au frontend de
    savoir s'il doit afficher un formulaire de connexion (ne revele jamais le
    token lui-meme, seulement deux booleens)."""
    return {
        "auth_required": _API_TOKEN is not None,
        "authenticated": _API_TOKEN is None or session_cookie == _API_TOKEN,
    }


def _run_propose(**kwargs: Any) -> Any:
    """Meme principe que `_run_generate` pour la proposition de nom (erreurs
    utilisateur en 400, le reste journalise et renvoye en 500)."""
    try:
        return engine.propose_release_name(**kwargs)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erreur inattendue pendant la proposition de nom")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.") from exc


def _run_generate(**kwargs: Any) -> str:
    """Appelle `engine.generate` en separant les erreurs utilisateur (entree
    invalide : profil/categorie inconnue, regle de nommage non respectee...)
    des erreurs serveur inattendues. Les premieres sont renvoyees telles
    quelles (400, message utile au client) ; les secondes sont journalisees
    cote serveur et renvoyees sous un message generique (500, pas de fuite de
    details internes)."""
    try:
        return engine.generate(**kwargs)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Erreur inattendue pendant la generation du NFO")
        raise HTTPException(status_code=500, detail="Erreur interne du serveur.") from exc


def _run_store(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Meme principe que `_run_generate` pour les operations de gestion de
    profil : erreurs utilisateur (`ProfileStoreError` — nom invalide,
    NFOGEN_PROFILES_DIR non configuree, rules.json non conforme au schema...)
    en 400, le reste en 500 (journalise, message generique)."""
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
    """Liste des profils et categories disponibles."""
    return engine.list_available()


class JsonRequest(BaseModel):
    category: str
    profile: str = "c411"
    data: dict[str, Any] = {}
    options: dict[str, Any] = {}


def _header_safe(value: str) -> str:
    """Retire tout caractere de controle (CR/LF inclus) et les guillemets/
    antislash d'une valeur destinee a un en-tete HTTP (`Content-Disposition`).

    Le serveur ASGI (uvicorn) rejette deja une injection CRLF au niveau
    protocole (`HEADER_VALUE_RE`), mais on ne doit pas en dependre : une
    valeur fournie par l'utilisateur (`release_name`...) ne doit jamais
    pouvoir atteindre un en-tete sans normalisation explicite ici, quel que
    soit le serveur ASGI utilise. Guillemets/antislash retires en plus pour
    rester bien forme dans `filename="..."` (chaine entre guillemets)."""
    return "".join(c for c in value if ord(c) >= 0x20 and c != "\x7f" and c not in '"\\')


def _filename(category: str, data: dict, declared_by_profile: str | None) -> str:
    """Nom de fichier pour le header Content-Disposition.

    Si le profil/categorie impose un nom (regle `register_filename`), on
    l'utilise tel quel (apres normalisation pour l'en-tete, cf. `_header_safe`) :
    c'est la seule source de verite sur le nommage, l'API ne doit pas
    reinventer sa propre heuristique. Sinon, repli generique (pas de
    convention a respecter pour ce profil/categorie).
    """
    if declared_by_profile:
        name = declared_by_profile
    else:
        base = data.get("title") or data.get("album") or category
        safe = "".join(c if c.isalnum() or c in "-._ " else "_" for c in str(base)).strip()
        name = f"{safe or category}.nfo"
    return _header_safe(name)


@app.post("/generate/json", dependencies=[Depends(require_token_for_generate)])
def generate_json(req: JsonRequest, download: bool = Query(False)) -> Any:
    """Genere un NFO a partir de metadonnees JSON (sans fichier)."""
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


@app.post("/propose-name", dependencies=[Depends(require_token_for_generate)])
def propose_name(req: NameProposalRequest) -> dict[str, Any]:
    """Suggere un release_name a partir des NOMS de fichiers (jamais leur
    contenu : aucun upload necessaire) et, optionnellement, du tag `Title`
    embarque dans chaque conteneur video (`title_hints`, deja extrait par le
    client, ex. via mediainfo.js cote navigateur) : utilisable des la
    selection des fichiers dans un client (cf. frontend, page Generer)."""
    proposal = _run_propose(
        category=req.category,
        profile=req.profile,
        filenames=req.filenames,
        title_hints=req.title_hints,
    )
    return {"name": proposal.name, "fields": proposal.fields, "warnings": proposal.warnings}


@app.post("/generate", dependencies=[Depends(require_token_for_generate)])
async def generate_upload(
    category: Optional[str] = Form(None),
    profile: str = Form("c411"),
    data: str = Form("{}"),
    options: str = Form("{}"),
    files: list[UploadFile] = File(default_factory=list),
    download: bool = Query(False),
) -> Any:
    """Genere un NFO a partir de fichier(s) uploade(s) + metadonnees optionnelles.

    - 1 fichier video  -> categorie 'video' (auto-detectee si non precisee)
    - plusieurs fichiers audio -> categorie 'audio' (album)
    """
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
            # Path(...).name isole le dernier segment (pas de "../" possible)
            # mais ".."/"." eux-memes restent litteralement leur propre .name
            # (Path("..").name == ".."), donc un nom de fichier upload egal a
            # ".." ecrirait dans le PARENT du dossier temporaire sans ce
            # garde-fou explicite -- a verifier en plus du seul appel a .name.
            candidate_name = Path(up.filename or "").name
            if not candidate_name or candidate_name in (".", ".."):
                candidate_name = f"upload_{index}.bin"
            dest = tmp_path / candidate_name
            # Ecriture par blocs : un fichier source (video, jeu, scan...) peut
            # peser plusieurs centaines de Go, hors de question de le charger
            # entierement en memoire avant de l'ecrire sur disque. Le total
            # ecrit est en plus compte ici et compare a _MAX_UPLOAD_BYTES :
            # le middleware `_limit_upload_size` ne fait foi que du
            # Content-Length DECLARE par le client (un client malhonnete ou un
            # transfert chunked sans Content-Length le contournerait
            # entierement) -- ce compteur applique la meme limite sur les
            # octets REELLEMENT ecrits sur disque, seule mesure fiable.
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

        # Source : un dossier si plusieurs fichiers (album), sinon le fichier seul.
        if not saved:
            source = None
        elif len(saved) == 1:
            source = saved[0]
        else:
            source = tmp_path

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


# --------------------------------------------------------------------------- #
# Gestion des profils utilisateur (NFOGEN_PROFILES_DIR) : creer/editer/
# supprimer un profil declaratif (rules.json + templates) sans toucher au
# profil livre avec le paquet (C411, lecture seule). Toutes ces routes
# exigent le token API (`require_token`) comme /generate et /generate/json.
# --------------------------------------------------------------------------- #
class ProfileWriteRequest(BaseModel):
    rules: dict[str, Any] = {}
    templates: dict[str, str] = {}


@app.get("/profiles/store", dependencies=[Depends(require_token)])
def list_managed_profiles() -> list[str]:
    """Noms des profils utilisateur presents dans NFOGEN_PROFILES_DIR."""
    return _run_store(profile_store.list_profiles)


@app.get("/profiles/store/{name}", dependencies=[Depends(require_token)])
def read_managed_profile(name: str) -> dict[str, Any]:
    """Regles (`rules.json`) et templates (`.j2`) d'un profil utilisateur."""
    return _run_store(profile_store.read_profile, name)


@app.put("/profiles/store/{name}", dependencies=[Depends(require_token)])
def write_managed_profile(name: str, req: ProfileWriteRequest) -> dict[str, str]:
    """Cree le profil s'il n'existe pas, le remplace entierement sinon. Les
    regles sont validees contre le schema (`rules.schema.json`) avant toute
    ecriture sur disque ; le profil est immediatement utilisable (pas de
    redemarrage necessaire)."""
    _run_store(profile_store.write_profile, name, rules=req.rules, templates=req.templates)
    return {"status": "ok", "name": name}


@app.delete("/profiles/store/{name}", dependencies=[Depends(require_token)])
def delete_managed_profile(name: str) -> dict[str, str]:
    _run_store(profile_store.delete_profile, name)
    return {"status": "ok", "name": name}


@app.get("/profiles/store/{name}/export", dependencies=[Depends(require_token)])
def export_managed_profile(name: str) -> Response:
    """Archive `.zip` du profil (meme structure que sur disque), prete a
    etre partagee ou versionnee dans un depot git."""
    content = _run_store(profile_store.export_profile_zip, name)
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


@app.post("/profiles/store/{name}/import", dependencies=[Depends(require_token)])
async def import_managed_profile(name: str, file: UploadFile = File(...)) -> dict[str, str]:
    """Cree/remplace un profil a partir d'un `.zip` (produit par l'export
    ci-dessus, ou construit a la main avec la meme structure)."""
    content = await file.read()
    _run_store(profile_store.import_profile_zip, name, content)
    return {"status": "ok", "name": name}


# --------------------------------------------------------------------------- #
# Frontend buildé, optionnel (NFOGEN_FRONTEND_DIST) — deploiement "tout-en-un"
# --------------------------------------------------------------------------- #
# Enregistree EN DERNIER : toutes les routes API ci-dessus restent
# prioritaires, cette route generique ne recoit que ce qu'aucune d'elles n'a
# matche (cf. ordre de resolution des routes Starlette/FastAPI).
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
        """Sert le frontend (SPA) : un fichier statique reel (favicon...) tel
        quel, sinon `index.html` pour laisser React Router decider cote
        navigateur quelle page afficher (deep link sur /settings, /profils...).

        `full_path` vient directement de l'URL (non fiable) : on resout les
        liens symboliques et les `..` (`os.path.realpath`) puis on verifie
        que le resultat reste sous `_FRONTEND_DIR_REAL` (prefixe se terminant
        par le separateur, pour ne pas confondre un dossier voisin de meme
        prefixe, ex. `frontend_dist_evil`) AVANT tout acces disque -- sans
        ca, une requete comme `GET /../../etc/passwd` pourrait lire n'importe
        quel fichier lisible par le processus, sur une route sans
        authentification."""
        candidate = os.path.realpath(os.path.join(str(_FRONTEND_DIR), full_path))
        if full_path and candidate.startswith(_FRONTEND_DIR_REAL) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIR / "index.html")
