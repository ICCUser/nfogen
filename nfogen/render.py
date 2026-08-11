"""Moteur de rendu base sur Jinja2.

Trois sources de templates, dans l'ordre de priorite (`ChoiceLoader`) :
1. `extra_dirs` (parametre explicite) ;
2. `NFOGEN_TEMPLATES` (surcharge externe, `<dir>/<profil>/<cat>.j2`) ;
3. `NFOGEN_PROFILES_DIR` (profils utilisateur, `<dir>/<profil>/templates/<cat>.j2`) ;
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
    """Un profil = un sous-dossier de `root` avec un dossier `templates/`."""
    mapping = {
        entry.name: FileSystemLoader(str(entry / "templates"))
        for entry in sorted(root.iterdir())
        if entry.is_dir() and (entry / "templates").is_dir()
    }
    return PrefixLoader(mapping)


@lru_cache(maxsize=None)
def _env(extra: tuple[str, ...] = ()) -> SandboxedEnvironment:
    search_dirs: list[str] = list(extra)
    env_dir = os.environ.get("NFOGEN_TEMPLATES")
    if env_dir:
        search_dirs.append(env_dir)

    loaders = [FileSystemLoader(d) for d in search_dirs]

    profiles_dir = os.environ.get("NFOGEN_PROFILES_DIR")
    if profiles_dir and Path(profiles_dir).is_dir():
        loaders.append(_profiles_loader(Path(profiles_dir)))

    loaders.append(_profiles_loader(_PACKAGE_PROFILES_DIR))

    # Sandbox : indispensable des qu'un template peut venir d'un dossier
    # externe plutot que d'etre livre avec le code.
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
