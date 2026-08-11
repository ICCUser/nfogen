"""Profils disponibles.

Importer ce paquet enregistre les profils livres avec nfogen (C411) et les
profils utilisateur trouves dans `NFOGEN_PROFILES_DIR` (meme mecanisme
declaratif que C411, voir `nfogen.declarative_profile`).

Un profil utilisateur peut porter le meme nom qu'un profil livre : il le
surcharge entierement. C'est ce que fait `nfogen.profile_store` via
`BUILTIN_PROFILE_DIRS` ci-dessous.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from ..declarative_profile import register_declarative_profile
from ..registry import unregister_profile
from . import c411  # noqa: F401  (auto-enregistrement)

logger = logging.getLogger("nfogen.profiles")

__all__ = ["c411", "BUILTIN_PROFILE_DIRS"]

BUILTIN_PROFILE_DIRS: dict[str, Path] = {"c411": Path(__file__).parent / "c411"}


def _load_external_profiles() -> None:
    root = os.environ.get("NFOGEN_PROFILES_DIR")
    if not root:
        return
    root_path = Path(root)
    if not root_path.is_dir():
        logger.warning("NFOGEN_PROFILES_DIR='%s' n'est pas un dossier existant, ignore.", root)
        return

    for entry in sorted(root_path.iterdir()):
        if not entry.is_dir():
            continue
        rules_file = entry / "rules.json"
        try:
            rules = json.loads(rules_file.read_text(encoding="utf-8")) if rules_file.is_file() else {}
            unregister_profile(entry.name)
            register_declarative_profile(entry.name, rules)
        except Exception:
            logger.exception("Profil utilisateur '%s' invalide, ignore.", entry.name)


_load_external_profiles()
