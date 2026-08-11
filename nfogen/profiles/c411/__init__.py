"""Profil C411 : chargement du profil declaratif de reference.

Aucune logique specifique a C411 ici : tout vit dans `rules.json` et
`templates/*.j2`, interpretes par `nfogen.declarative_profile`. Pour ajuster
une regle ou un rendu, editer ces fichiers, jamais ce module.
"""
from __future__ import annotations

import json
from pathlib import Path

from ...declarative_profile import register_declarative_profile

_RULES = json.loads((Path(__file__).parent / "rules.json").read_text(encoding="utf-8"))

register_declarative_profile("c411", _RULES)
