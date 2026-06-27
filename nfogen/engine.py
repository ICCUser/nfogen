"""Coeur d'orchestration : resout le profil/categorie et produit le NFO."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from . import extract
from . import profiles as _profiles  # noqa: F401  (import => enregistre les profils)
from .models import RenderContext
from .name_proposal import NameProposal
from .registry import available, get_filename_rule, get_name_proposal_rule, get_renderer, get_validator

# Mapping extension -> categorie, pour la detection automatique. VIDEO_EXTS
# vient de extract.py (source unique) pour rester synchronise avec ce que
# l'extraction video sait effectivement lire.
_VIDEO_EXTS = extract.VIDEO_EXTS
_AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma"}
_EBOOK_EXTS = {".epub", ".pdf", ".cbr", ".cbz", ".mobi", ".azw3", ".djvu"}
_PRINT3D_EXTS = {".stl", ".3mf", ".obj", ".gcode", ".step", ".stp"}


def detect_category(source: Path) -> Optional[str]:
    """Devine la categorie a partir de l'extension (ou du contenu d'un dossier)."""
    source = Path(source)
    if source.is_dir():
        exts = {p.suffix.lower() for p in source.rglob("*") if p.is_file()}
        if exts & _AUDIO_EXTS:
            return "audio"
        if exts & _PRINT3D_EXTS:
            return "print3d"
        if exts & _EBOOK_EXTS:
            return "ebook"
        if exts & _VIDEO_EXTS:
            return "video"
        return None
    ext = source.suffix.lower()
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _EBOOK_EXTS:
        return "ebook"
    if ext in _PRINT3D_EXTS:
        return "print3d"
    return None


def generate(
    *,
    category: Optional[str] = None,
    profile: str = "c411",
    source: Optional[Path | str] = None,
    data: Optional[dict[str, Any]] = None,
    options: Optional[dict[str, Any]] = None,
    warnings: Optional[list[str]] = None,
    filename: Optional[list[str]] = None,
) -> str:
    """Genere le contenu d'un fichier NFO.

    Args:
        category: typologie (video/audio/game/ebook/print3d...). Si None et
            qu'une source est fournie, tente une detection automatique.
        profile: profil de regles a appliquer (defaut "c411").
        source: fichier ou dossier source (optionnel si `data` suffit).
        data: metadonnees fournies par l'appelant (completent/surchargent).
        options: options de rendu.
        warnings: liste optionnelle a remplir avec les avertissements non
            bloquants du validateur du profil/categorie (ex. langue audio
            manquante). Le validateur s'execute toujours s'il existe, que
            cette liste soit fournie ou non : les exigences obligatoires
            (ex. nommage de la release) levent une exception qui interrompt
            la generation ; seuls les avertissements informatifs sont
            optionnellement collectes ici.
        filename: liste optionnelle a remplir avec le nom de fichier impose
            par la regle de nommage du profil/categorie, si elle existe (ex.
            "Kaamelott.S05....nfo"). Vide si aucune regle n'est enregistree
            pour ce couple (profil, categorie) : l'appelant choisit alors le
            nom librement.

    Returns:
        Le texte du NFO (str).
    """
    src = Path(source) if source is not None else None
    if category is None:
        if src is None:
            raise ValueError("Categorie absente et aucune source pour la detecter.")
        category = detect_category(src)
        if category is None:
            raise ValueError(f"Categorie indeterminable pour : {src}")

    renderer = get_renderer(profile, category)
    ctx = RenderContext(
        profile=profile.lower(),
        category=category.lower(),
        source=src,
        data=dict(data or {}),
        options=dict(options or {}),
    )
    nfo = renderer(ctx)

    validator = get_validator(profile, category)
    if validator is not None:
        msgs = validator(ctx, nfo)
        if warnings is not None:
            warnings.extend(msgs)

    rule = get_filename_rule(profile, category)
    if rule is not None and filename is not None:
        filename.append(rule(ctx))

    return nfo


def propose_release_name(
    *,
    category: str,
    profile: str = "c411",
    filenames: list[str],
    title_hints: list[str | None] | None = None,
) -> NameProposal:
    """Propose un `release_name` a partir des noms de fichiers (aucune
    lecture de contenu necessaire : utilisable avant tout upload), et
    optionnellement des tags `Title` embarques dans les conteneurs video
    (`title_hints`, meme ordre/longueur que `filenames`) quand ils sont deja
    connus (ex. extraits cote navigateur) -- plus fiables que le nom de
    fichier seul pour la resolution/le codec/l'equipe. Leve une ValueError si
    ce profil/categorie n'a pas de proposition configuree (`name_proposal`
    absent du `rules.json` -- pas une erreur de saisie, une fonctionnalite
    non disponible pour ce profil)."""
    rule = get_name_proposal_rule(profile, category)
    if rule is None:
        raise ValueError(
            f"Aucune proposition de nom disponible pour profil='{profile}' categorie='{category}' "
            "(name_proposal non configure dans rules.json)."
        )
    return rule(filenames, title_hints)


def list_available() -> dict[str, list[str]]:
    return available()
