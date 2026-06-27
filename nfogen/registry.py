"""Registre des profils.

Un renderer est une fonction `(RenderContext) -> str` enregistree pour un
couple (profil, categorie). Ajouter un nouveau tracker = ecrire un module qui
appelle `@register("mon_profil", "video")`, sans modifier le coeur.

Un validateur est une fonction `(RenderContext, str) -> list[str]` optionnelle
enregistree pour le meme couple (profil, categorie). Elle recoit le contexte
et le NFO deja rendu, et renvoie une liste d'avertissements (vide si tout est
conforme aux exigences du profil). Une exception levee dans un validateur
interrompt la generation (regle obligatoire) ; les avertissements renvoyes
sont seulement informatifs et ne bloquent jamais.

Une regle de nommage est une fonction `(RenderContext) -> str` optionnelle,
enregistree elle aussi pour le meme couple. Elle impose le nom du fichier
.nfo final (ex. a partir de `ctx.data["release_name"]`). Quand elle existe,
c'est elle qui decide du nom — jamais le coeur, qui ne connait aucune
convention de nommage de tracker.

Un point d'extension optionnel supplementaire propose un `release_name` a
partir des seuls noms de fichiers (pas leur contenu), pour assister la saisie
sans demander d'upload (voir `nfogen.name_proposal`). Contrairement aux 3
autres, il n'est pas applicable a tous les profils : un profil sans
proposition enregistree renvoie simplement `None`.

Ces points d'extension (rendu, validation, nommage, proposition de nom) sont
la seule maniere de faire varier le comportement par profil : le coeur
(engine.py) ne fait jamais de branchement specifique a un tracker, il se
contente d'appeler ce qui est enregistre pour (profil, categorie).
"""
from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from .models import RenderContext
from .name_proposal import NameProposal

Renderer = Callable[[RenderContext], str]
Validator = Callable[[RenderContext, str], list[str]]
FilenameRule = Callable[[RenderContext], str]
# Le 2e argument (title_hints) est optionnel : une liste de tags `Title`
# embarques dans les conteneurs video, meme ordre/longueur que les noms de
# fichiers, ou None si non disponibles (cf. nfogen.name_proposal).
NameProposalRule = Callable[..., NameProposal]

_REGISTRY: Dict[Tuple[str, str], Renderer] = {}
_VALIDATORS: Dict[Tuple[str, str], Validator] = {}
_FILENAMES: Dict[Tuple[str, str], FilenameRule] = {}
_NAME_PROPOSALS: Dict[Tuple[str, str], NameProposalRule] = {}


def register(profile: str, category: str) -> Callable[[Renderer], Renderer]:
    """Decorateur d'enregistrement d'un renderer."""

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
    """Decorateur d'enregistrement d'un validateur (controle post-rendu)."""

    def decorator(func: Validator) -> Validator:
        key = (profile.lower(), category.lower())
        if key in _VALIDATORS:
            raise ValueError(f"Validateur deja enregistre pour {key}")
        _VALIDATORS[key] = func
        return func

    return decorator


def get_validator(profile: str, category: str) -> Optional[Validator]:
    """Renvoie le validateur enregistre pour (profil, categorie), ou None."""
    return _VALIDATORS.get((profile.lower(), category.lower()))


def register_filename(profile: str, category: str) -> Callable[[FilenameRule], FilenameRule]:
    """Decorateur d'enregistrement d'une regle de nommage du fichier NFO."""

    def decorator(func: FilenameRule) -> FilenameRule:
        key = (profile.lower(), category.lower())
        if key in _FILENAMES:
            raise ValueError(f"Regle de nommage deja enregistree pour {key}")
        _FILENAMES[key] = func
        return func

    return decorator


def get_filename_rule(profile: str, category: str) -> Optional[FilenameRule]:
    """Renvoie la regle de nommage enregistree pour (profil, categorie), ou None."""
    return _FILENAMES.get((profile.lower(), category.lower()))


def register_name_proposal(profile: str, category: str) -> Callable[[NameProposalRule], NameProposalRule]:
    """Decorateur d'enregistrement d'une proposition de `release_name` a
    partir de noms de fichiers (pas leur contenu, cf. `nfogen.name_proposal`)."""

    def decorator(func: NameProposalRule) -> NameProposalRule:
        key = (profile.lower(), category.lower())
        if key in _NAME_PROPOSALS:
            raise ValueError(f"Proposition de nom deja enregistree pour {key}")
        _NAME_PROPOSALS[key] = func
        return func

    return decorator


def get_name_proposal_rule(profile: str, category: str) -> Optional[NameProposalRule]:
    """Renvoie la regle de proposition de nom enregistree pour (profil,
    categorie), ou None si ce profil n'en propose pas."""
    return _NAME_PROPOSALS.get((profile.lower(), category.lower()))


def available() -> Dict[str, list[str]]:
    """Renvoie {profil: [categories...]} pour introspection (CLI/API)."""
    out: Dict[str, list[str]] = {}
    for prof, cat in sorted(_REGISTRY):
        out.setdefault(prof, []).append(cat)
    return out


def unregister_profile(profile: str) -> None:
    """Retire toutes les inscriptions (renderer/validateur/regle de nommage,
    toutes categories) d'un profil. Reserve a la gestion dynamique des
    profils utilisateur (creation/modification/suppression sans redemarrer le
    processus, voir `nfogen.profile_store`) : permet de re-enregistrer un
    profil modifie sans heurter le garde-fou "deja enregistre" des fonctions
    `register*` ci-dessus."""
    key_profile = profile.lower()
    for registry_dict in (_REGISTRY, _VALIDATORS, _FILENAMES, _NAME_PROPOSALS):
        for key in [k for k in registry_dict if k[0] == key_profile]:
            del registry_dict[key]
