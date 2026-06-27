"""Moteur de rendu base sur Jinja2.

Les profils structures (audio, jeux, ebook, impression 3D) sont decrits par
des templates `.j2`. On peut surcharger/ajouter des templates sans toucher au
code via un dossier externe (variable d'environnement `NFOGEN_TEMPLATES` ou
parametre `extra_dirs`). C'est le pilier de la modularite demandee.

Trois sources de templates, dans l'ordre de priorite (`ChoiceLoader` essaie
chacune et garde la premiere qui matche) :
1. `extra_dirs` (parametre explicite) ;
2. `NFOGEN_TEMPLATES` (surcharge externe, structure `<dir>/<profil>/<cat>.j2`) ;
3. `NFOGEN_PROFILES_DIR` (profils utilisateur geres dynamiquement, Phase 2 —
   structure `<dir>/<profil>/templates/<cat>.j2`, comme un profil embarque) ;
4. les profils embarques dans le paquet (`profiles/<profil>/templates/`).
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from jinja2 import ChoiceLoader, FileSystemLoader, PrefixLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from . import formats

_PACKAGE_PROFILES_DIR = Path(__file__).parent / "profiles"


def _profiles_loader(root: Path) -> PrefixLoader:
    """Un profil = un sous-dossier de `root` avec un dossier `templates/`.
    Le prefixe (`<profil>/...`) correspond exactement a la cle utilisee par
    `render_template()` ci-dessous. Reutilise aussi bien pour les profils
    embarques dans le paquet que pour `NFOGEN_PROFILES_DIR`."""
    mapping = {
        entry.name: FileSystemLoader(str(entry / "templates"))
        for entry in sorted(root.iterdir())
        if entry.is_dir() and (entry / "templates").is_dir()
    }
    return PrefixLoader(mapping)


@lru_cache(maxsize=None)
def _env(extra: tuple[str, ...] = ()) -> SandboxedEnvironment:
    search_dirs: list[str] = []
    # 1) dossiers externes explicites (priorite la plus haute)
    search_dirs.extend(extra)
    # 2) dossier defini par l'environnement
    env_dir = os.environ.get("NFOGEN_TEMPLATES")
    if env_dir:
        search_dirs.append(env_dir)

    loaders = [FileSystemLoader(d) for d in search_dirs]

    # 3) profils utilisateur (NFOGEN_PROFILES_DIR), s'il est configure
    profiles_dir = os.environ.get("NFOGEN_PROFILES_DIR")
    if profiles_dir and Path(profiles_dir).is_dir():
        loaders.append(_profiles_loader(Path(profiles_dir)))

    # 4) profils embarques dans le paquet
    loaders.append(_profiles_loader(_PACKAGE_PROFILES_DIR))

    # Sandbox : indispensable des qu'un template peut venir d'un dossier
    # externe (NFOGEN_TEMPLATES, et demain les profils utilisateur de la
    # Phase 2) plutot que d'etre livre avec le code. Bloque l'acces aux
    # attributs/methodes dangereux (ex. `__class__`, mutation d'objets
    # internes) sans rien changer pour les templates "normaux" ci-dessus.
    env = SandboxedEnvironment(
        loader=ChoiceLoader(loaders),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,
    )
    env.filters["dotpad"] = formats.dotpad
    env.filters["colonpad"] = formats.colonpad
    env.filters["human_bin"] = formats.human_size_bin
    env.filters["human_dec"] = formats.human_size_dec
    env.filters["mmss"] = formats.mmss
    env.globals["banner"] = formats.banner
    return env


def render_template(
    profile: str,
    category: str,
    context: dict[str, Any],
    *,
    extra_dirs: Optional[list[str]] = None,
) -> str:
    """Rend le template `<profile>/<category>.j2` avec le contexte fourni."""
    env = _env(tuple(extra_dirs or ()))
    template = env.get_template(f"{profile}/{category}.j2")
    out = template.render(**context)
    return out.replace("\r\n", "\n").rstrip("\n") + "\n"
