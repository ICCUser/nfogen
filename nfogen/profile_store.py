"""Stockage sur disque des profils utilisateur (`NFOGEN_PROFILES_DIR`).

Un profil utilisateur est un dossier `<NFOGEN_PROFILES_DIR>/<nom>/` contenant
un `rules.json` (optionnel) et un dossier `templates/` (fichiers
`<categorie>.j2`) -- meme structure qu'un profil embarque comme
`nfogen/profiles/c411/`. Ne connait rien de HTTP : utilisable par l'API et la CLI.

Un profil livre avec le paquet (voir `nfogen.profiles.BUILTIN_PROFILE_DIRS`)
reste lisible/exportable ici meme sans avoir ete surcharge. L'ecrire cree un
profil utilisateur du meme nom qui prend le dessus ; le supprimer restaure
l'enregistrement du profil livre.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import threading
import zipfile
from pathlib import Path
from typing import Any

from . import rules as rules_engine
from .declarative_profile import CATEGORIES, register_declarative_profile
from .registry import unregister_profile

# Verrou unique sur tout acces disque a un profil (lecture ET ecriture) :
# evite qu'une lecture tombe sur un dossier partiellement ecrit, ou que deux
# ecritures concurrentes sur le meme profil se marchent dessus.
_LOCK = threading.Lock()

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_TEMPLATE_FILENAMES = {category: f"{category}.j2" for category in CATEGORIES}


class ProfileStoreError(ValueError):
    """Erreur utilisateur (entree invalide) : a traduire en HTTP 400 cote API."""


def _root() -> Path:
    root = os.environ.get("NFOGEN_PROFILES_DIR")
    if not root:
        raise ProfileStoreError(
            "NFOGEN_PROFILES_DIR n'est pas configuree : aucun profil utilisateur ne peut etre gere."
        )
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _check_name(name: str) -> None:
    if not _NAME_RE.match(name or ""):
        raise ProfileStoreError(
            f"Nom de profil invalide : '{name}' (lettres/chiffres/'-'/'_' uniquement)."
        )


def _profile_dir(name: str, *, must_exist: bool) -> Path:
    _check_name(name)
    path = _root() / name
    if must_exist and not path.is_dir():
        raise ProfileStoreError(f"Profil utilisateur inconnu : '{name}'.")
    return path


def list_profiles() -> list[str]:
    """Profils utilisateur presents dans NFOGEN_PROFILES_DIR (pas les profils livres)."""
    return sorted(p.name for p in _root().iterdir() if p.is_dir())


def _resolve_readable_dir(name: str) -> Path:
    """Dossier source d'un profil existant : utilisateur, sinon livre avec le paquet."""
    _check_name(name)
    root = os.environ.get("NFOGEN_PROFILES_DIR")
    if root:
        managed = Path(root) / name
        if managed.is_dir():
            return managed
    from .profiles import BUILTIN_PROFILE_DIRS

    builtin = BUILTIN_PROFILE_DIRS.get(name)
    if builtin is not None:
        return builtin
    raise ProfileStoreError(f"Profil inconnu : '{name}'.")


def _read_rules_and_templates(path: Path) -> dict[str, Any]:
    rules_file = path / "rules.json"
    rules = json.loads(rules_file.read_text(encoding="utf-8")) if rules_file.is_file() else {}
    templates_dir = path / "templates"
    templates = {
        f.stem: f.read_text(encoding="utf-8")
        for f in sorted(templates_dir.glob("*.j2"))
    } if templates_dir.is_dir() else {}
    return {"rules": rules, "templates": templates}


def read_profile(name: str) -> dict[str, Any]:
    with _LOCK:
        path = _resolve_readable_dir(name)
        return {"name": name, **_read_rules_and_templates(path)}


def write_profile(name: str, *, rules: dict[str, Any], templates: dict[str, str]) -> None:
    """Cree ou remplace un profil : valide avant d'ecrire, rien ne touche le disque en cas d'erreur."""
    try:
        rules_engine.validate_rules_document(rules)
    except ValueError as exc:
        raise ProfileStoreError(str(exc)) from exc
    for category in templates:
        if category not in CATEGORIES:
            raise ProfileStoreError(
                f"Categorie de template inconnue : '{category}' (attendu : {', '.join(CATEGORIES)})."
            )

    with _LOCK:
        path = _profile_dir(name, must_exist=False)
        if path.exists():
            shutil.rmtree(path)
        templates_dir = path / "templates"
        templates_dir.mkdir(parents=True)
        (path / "rules.json").write_text(
            json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        for category, content in templates.items():
            try:
                filename = _TEMPLATE_FILENAMES[category]
            except KeyError:
                raise ProfileStoreError(f"Categorie de template inconnue : '{category}'.") from None
            (templates_dir / filename).write_text(content, encoding="utf-8")

        _reregister(name, rules)


def delete_profile(name: str) -> None:
    """Supprime un profil utilisateur ; restaure le profil livre du meme nom, s'il existe."""
    with _LOCK:
        path = _profile_dir(name, must_exist=True)
        shutil.rmtree(path)
        unregister_profile(name)

        from .profiles import BUILTIN_PROFILE_DIRS

        builtin_dir = BUILTIN_PROFILE_DIRS.get(name)
        if builtin_dir is not None:
            register_declarative_profile(name, _read_rules_and_templates(builtin_dir)["rules"])
        _clear_template_cache()


def export_profile_zip(name: str) -> bytes:
    """Empaquette rules.json + templates/*.j2 en .zip (jamais __init__.py/__pycache__)."""
    with _LOCK:
        path = _resolve_readable_dir(name)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            rules_file = path / "rules.json"
            if rules_file.is_file():
                zf.write(rules_file, "rules.json")
            templates_dir = path / "templates"
            if templates_dir.is_dir():
                for f in sorted(templates_dir.glob("*.j2")):
                    zf.write(f, f"templates/{f.name}")
        return buf.getvalue()


def import_profile_zip(name: str, content: bytes) -> None:
    """Cree/remplace un profil a partir d'un .zip produit par `export_profile_zip`."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
            rules: dict[str, Any] = {}
            if "rules.json" in names:
                rules = json.loads(zf.read("rules.json").decode("utf-8"))
            templates = {
                Path(n).stem: zf.read(n).decode("utf-8")
                for n in names
                if n.startswith("templates/") and n.endswith(".j2")
            }
    except zipfile.BadZipFile as exc:
        raise ProfileStoreError("Fichier .zip invalide.") from exc
    except json.JSONDecodeError as exc:
        raise ProfileStoreError(f"rules.json invalide dans l'archive : {exc}") from exc

    write_profile(name, rules=rules, templates=templates)


def _reregister(name: str, rules: dict[str, Any]) -> None:
    unregister_profile(name)
    register_declarative_profile(name, rules)
    _clear_template_cache()


def _clear_template_cache() -> None:
    """Les templates sont mis en cache (lru_cache) : a vider pour qu'un profil modifie soit visible."""
    from .render import _env

    _env.cache_clear()
