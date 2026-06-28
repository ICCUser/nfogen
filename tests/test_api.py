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
import zipfile

import pytest
from fastapi.testclient import TestClient

from nfogen import api as api_module
from nfogen.registry import unregister_profile


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
# Authentification par token
# --------------------------------------------------------------------------- #
def test_open_by_default_without_token(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN=None)
    client = TestClient(mod.app)
    resp = client.post("/generate/json", json=GAME_PAYLOAD)
    assert resp.status_code == 200


def test_blocks_without_token_when_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    resp = client.post("/generate/json", json=GAME_PAYLOAD)
    assert resp.status_code == 401


def test_blocks_with_wrong_token(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    resp = client.post(
        "/generate/json", json=GAME_PAYLOAD, headers={"Authorization": "Bearer mauvais"}
    )
    assert resp.status_code == 401


def test_allows_with_correct_token(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
    client = TestClient(mod.app)
    resp = client.post(
        "/generate/json", json=GAME_PAYLOAD, headers={"Authorization": "Bearer secret123"}
    )
    assert resp.status_code == 200


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
def test_propose_name_requires_token_when_configured(reload_api):
    mod = reload_api(NFOGEN_API_TOKEN="secret123")
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
