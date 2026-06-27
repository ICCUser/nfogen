"""Profils disponibles.

Importer ce paquet enregistre :
1) les profils livres avec nfogen (C411, voir `c411/`) ;
2) les profils utilisateur trouves dans `NFOGEN_PROFILES_DIR`, s'il est
   defini : un sous-dossier par profil, avec un `rules.json` optionnel
   (absent = profil sans regle de nommage, juste des templates) et un
   dossier `templates/`. Meme mecanisme generique que pour C411
   (`nfogen.declarative_profile`) : aucune ligne de Python necessaire pour
   ajouter ce type de profil.

Pour ajouter un nouveau profil livre *avec le paquet* (distinct d'un profil
utilisateur gere dynamiquement) : creer un dossier ici sur le modele de
`c411/` et l'importer ci-dessous.

Un profil utilisateur peut porter le meme nom qu'un profil livre (ex.
"c411") : il le surcharge entierement (regles + templates), exactement comme
`NFOGEN_TEMPLATES` surcharge des templates individuels. Aucun profil livre
n'est donc reellement "protege" — c'est juste l'etat par defaut tant
qu'aucun dossier utilisateur du meme nom n'existe.
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

__all__ = ["c411"]


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
            # Retire d'abord toute inscription existante (ex. le profil livre
            # du meme nom) : un profil utilisateur prend toujours le dessus,
            # meme apres un redemarrage du processus.
            unregister_profile(entry.name)
            register_declarative_profile(entry.name, rules)
        except Exception:
            logger.exception("Profil utilisateur '%s' invalide, ignore.", entry.name)


_load_external_profiles()
