"""Profil C411 : chargement du profil declaratif de reference.

Ce module ne contient plus aucune logique specifique a C411 : tout vit dans
`rules.json` (regles de nommage par categorie) et `templates/*.j2` (rendu),
interpretes par le moteur generique `nfogen.declarative_profile`. C'est
exactement le meme mecanisme que celui utilise pour charger un profil
utilisateur depuis `NFOGEN_PROFILES_DIR` (voir `nfogen/profiles/__init__.py`
et `nfogen/profile_store.py`) : C411 n'est qu'un cas particulier "livre avec
le paquet Python" plutot que "depose dans un dossier externe".

Pour ajuster une regle de nommage ou un rendu : editer `rules.json` ou les
fichiers `templates/*.j2` de ce dossier, jamais ce module.

Pour ajouter un nouveau profil livre avec le paquet (vs. un profil utilisateur
gere dynamiquement) : creer un dossier `profiles/<tracker>/` sur ce modele
(un `rules.json` + un dossier `templates/`, et ce meme `__init__.py` de 6
lignes en changeant juste le nom), puis l'importer dans `profiles/__init__.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

from ...declarative_profile import register_declarative_profile

_RULES = json.loads((Path(__file__).parent / "rules.json").read_text(encoding="utf-8"))

register_declarative_profile("c411", _RULES)
