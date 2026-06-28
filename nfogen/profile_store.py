"""Stockage sur disque des profils utilisateur (`NFOGEN_PROFILES_DIR`).

Un profil utilisateur est un dossier `<NFOGEN_PROFILES_DIR>/<nom>/` contenant
un `rules.json` (optionnel) et un dossier `templates/` (fichiers
`<categorie>.j2`) — exactement la structure d'un profil embarque comme
`nfogen/profiles/c411/`. Ce module ne fait que lire/ecrire ces fichiers et
(re)enregistrer le profil auprès du coeur via
`nfogen.declarative_profile.register_declarative_profile` ; il ne connait
rien de HTTP, pour rester utilisable aussi bien par l'API que par un futur
usage CLI.

Le profil livre avec le paquet (C411) n'est PAS gere ici : il est lecture
seule, vit dans le code source, et n'a pas a etre cree/modifie/supprime a
l'execution (voir ROADMAP.md, "Portee du frontend").
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from . import rules as rules_engine
from .declarative_profile import CATEGORIES, register_declarative_profile
from .registry import unregister_profile

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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
    """Noms des profils utilisateur presents dans NFOGEN_PROFILES_DIR."""
    return sorted(p.name for p in _root().iterdir() if p.is_dir())


def read_profile(name: str) -> dict[str, Any]:
    """Contenu d'un profil utilisateur : ses regles et le texte de chacun de
    ses templates, indexes par categorie."""
    path = _profile_dir(name, must_exist=True)
    rules_file = path / "rules.json"
    rules = json.loads(rules_file.read_text(encoding="utf-8")) if rules_file.is_file() else {}
    templates_dir = path / "templates"
    templates = {
        f.stem: f.read_text(encoding="utf-8")
        for f in sorted(templates_dir.glob("*.j2"))
    } if templates_dir.is_dir() else {}
    return {"name": name, "rules": rules, "templates": templates}


def write_profile(name: str, *, rules: dict[str, Any], templates: dict[str, str]) -> None:
    """Cree ou remplace entierement un profil utilisateur : valide le schema
    des regles, ecrit les fichiers sur disque, puis (re)enregistre le profil
    auprès du coeur. La validation a lieu avant toute ecriture : un rules.json
    invalide ne touche jamais le disque."""
    try:
        rules_engine.validate_rules_document(rules)
    except ValueError as exc:
        raise ProfileStoreError(str(exc)) from exc
    for category in templates:
        if category not in CATEGORIES:
            raise ProfileStoreError(
                f"Categorie de template inconnue : '{category}' (attendu : {', '.join(CATEGORIES)})."
            )

    path = _profile_dir(name, must_exist=False)
    if path.exists():
        shutil.rmtree(path)
    templates_dir = path / "templates"
    templates_dir.mkdir(parents=True)
    (path / "rules.json").write_text(json.dumps(rules, indent=2, ensure_ascii=False), encoding="utf-8")
    for category, content in templates.items():
        # `category` est revalide ici (pas seulement dans la boucle
        # ci-dessus) : le nom de fichier ecrit doit rester visiblement issu
        # d'une liste fixe (CATEGORIES), jamais d'une valeur arbitraire, pour
        # exclure toute traversee de chemin sans devoir faire confiance a une
        # validation distante dans la fonction.
        if category not in CATEGORIES:
            raise ProfileStoreError(f"Categorie de template inconnue : '{category}'.")
        (templates_dir / f"{category}.j2").write_text(content, encoding="utf-8")

    _reregister(name, rules)


def delete_profile(name: str) -> None:
    """Supprime un profil utilisateur du disque et du registre."""
    path = _profile_dir(name, must_exist=True)
    shutil.rmtree(path)
    unregister_profile(name)
    _clear_template_cache()


def export_profile_zip(name: str) -> bytes:
    """Empaquette `rules.json` + `templates/*.j2` d'un profil utilisateur en
    `.zip` (meme structure que sur disque, prete a etre redeposee ailleurs ou
    versionnee dans un depot git)."""
    path = _profile_dir(name, must_exist=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(path.rglob("*")):
            if file.is_file():
                zf.write(file, file.relative_to(path).as_posix())
    return buf.getvalue()


def import_profile_zip(name: str, content: bytes) -> None:
    """Cree/remplace un profil utilisateur a partir d'un `.zip` produit par
    `export_profile_zip` (ou construit a la main avec la meme structure)."""
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
    """Les templates sont mis en cache par `render.py` (`lru_cache`) : un
    profil utilisateur cree/modifie/supprime doit etre visible immediatement,
    sans redemarrer le processus."""
    from .render import _env

    _env.cache_clear()
