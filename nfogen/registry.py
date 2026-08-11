"""Registre des profils.

Un renderer est une fonction `(RenderContext) -> str` enregistree pour un
couple (profil, categorie). Un validateur optionnel `(RenderContext, str) ->
list[str]` recoit le contexte et le NFO rendu, et renvoie des avertissements ;
une exception levee interrompt la generation. Une regle de nommage optionnelle
`(RenderContext) -> str` impose le nom du fichier `.nfo`. Une proposition de
nom optionnelle suggere un `release_name` a partir des noms de fichiers (voir
`nfogen.name_proposal`).

Ce sont les seuls points d'extension : `engine.py` ne fait jamais de
branchement specifique a un tracker.
"""
from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from .models import RenderContext
from .name_proposal import NameProposal

Renderer = Callable[[RenderContext], str]
Validator = Callable[[RenderContext, str], list[str]]
FilenameRule = Callable[[RenderContext], str]
NameProposalRule = Callable[..., NameProposal]

_REGISTRY: Dict[Tuple[str, str], Renderer] = {}
_VALIDATORS: Dict[Tuple[str, str], Validator] = {}
_FILENAMES: Dict[Tuple[str, str], FilenameRule] = {}
_NAME_PROPOSALS: Dict[Tuple[str, str], NameProposalRule] = {}


def register(profile: str, category: str) -> Callable[[Renderer], Renderer]:
    def decorator(func: Renderer) -> Renderer:
        key = (profile.lower(), category.lower())
        if key in _REGISTRY:
            raise ValueError(f"Renderer deja enregistre pour {key}")
        _REGISTRY[key] = func
        return func

    return decorator


def get_renderer(profile: str, category: str) -> Renderer:
    key = (profile.lower(), category.lower())
    if key not in _REGISTRY:
        raise KeyError(
            f"Aucun renderer pour profil='{profile}' categorie='{category}'. "
            f"Disponibles : {sorted(_REGISTRY)}"
        )
    return _REGISTRY[key]


def register_validator(profile: str, category: str) -> Callable[[Validator], Validator]:
    def decorator(func: Validator) -> Validator:
        key = (profile.lower(), category.lower())
        if key in _VALIDATORS:
            raise ValueError(f"Validateur deja enregistre pour {key}")
        _VALIDATORS[key] = func
        return func

    return decorator


def get_validator(profile: str, category: str) -> Optional[Validator]:
    return _VALIDATORS.get((profile.lower(), category.lower()))


def register_filename(profile: str, category: str) -> Callable[[FilenameRule], FilenameRule]:
    def decorator(func: FilenameRule) -> FilenameRule:
        key = (profile.lower(), category.lower())
        if key in _FILENAMES:
            raise ValueError(f"Regle de nommage deja enregistree pour {key}")
        _FILENAMES[key] = func
        return func

    return decorator


def get_filename_rule(profile: str, category: str) -> Optional[FilenameRule]:
    return _FILENAMES.get((profile.lower(), category.lower()))


def register_name_proposal(profile: str, category: str) -> Callable[[NameProposalRule], NameProposalRule]:
    def decorator(func: NameProposalRule) -> NameProposalRule:
        key = (profile.lower(), category.lower())
        if key in _NAME_PROPOSALS:
            raise ValueError(f"Proposition de nom deja enregistree pour {key}")
        _NAME_PROPOSALS[key] = func
        return func

    return decorator


def get_name_proposal_rule(profile: str, category: str) -> Optional[NameProposalRule]:
    return _NAME_PROPOSALS.get((profile.lower(), category.lower()))


def available() -> Dict[str, list[str]]:
    """Renvoie {profil: [categories...]} pour introspection (CLI/API)."""
    out: Dict[str, list[str]] = {}
    for prof, cat in sorted(_REGISTRY):
        out.setdefault(prof, []).append(cat)
    return out


def unregister_profile(profile: str) -> None:
    """Retire toutes les inscriptions d'un profil (creation/modification a chaud)."""
    key_profile = profile.lower()
    for registry_dict in (_REGISTRY, _VALIDATORS, _FILENAMES, _NAME_PROPOSALS):
        for key in [k for k in registry_dict if k[0] == key_profile]:
            del registry_dict[key]
