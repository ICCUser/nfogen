"""Enregistrement generique d'un profil 100% declaratif.

Un profil "declaratif" ne contient aucune ligne de Python qui lui soit
propre : il fournit seulement un `rules.json` (regles de nommage par
categorie, voir `nfogen/rules.py`) et des templates `.j2` (voir
`nfogen/render.py`). Ce module sait construire, pour les 5 categories fixes
du coeur (`CATEGORIES`), les fonctions de rendu/validation/nommage et les
enregistrer auprès de `nfogen.registry` — c'est la SEULE fonction que ce
module expose : `register_declarative_profile(profile, rules)`.

C'est le mecanisme utilise pour :
- le profil livre avec le paquet (`nfogen/profiles/c411/__init__.py`, qui
  n'est plus qu'un point d'entree appelant cette fonction) ;
- les profils utilisateur charges depuis `NFOGEN_PROFILES_DIR`
  (`nfogen/profiles/__init__.py`) ou geres via l'API (`nfogen/profile_store.py`).

Ajouter un profil ne demande donc jamais de toucher ce fichier : seulement un
`rules.json` + des `.j2`. La seule logique vraiment "cablee" ici est le choix
de la source de donnees par categorie (lire un fichier video via MediaInfo,
un dossier audio via mutagen, ou juste scanner des fichiers) — c'est une
question de *type de contenu*, pas de *profil*, donc strictement generique.
"""
from __future__ import annotations

from typing import Any, Callable

from . import extract, formats
from . import name_proposal as name_proposal_engine
from . import rules as rules_engine
from .models import RenderContext
from .registry import register, register_filename, register_name_proposal, register_validator
from .render import render_template

CATEGORIES = ("video", "audio", "game", "ebook", "print3d")

_SCAN_DEFAULTS: dict[str, dict[str, Any]] = {
    "game": {"languages_audio": "", "languages_text": "", "requirements": {}, "install_steps": []},
}


def _merge(auto: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Fusionne donnees auto-extraites et donnees fournies (data prioritaire)."""
    merged = dict(auto)
    for key, value in data.items():
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged


def _make_render_video(profile: str) -> Callable[[RenderContext], str]:
    def render_video(ctx: RenderContext) -> str:
        raw = ctx.data.get("raw_text")
        if not raw:
            if ctx.source is None:
                raise ValueError("Profil video : fournir un fichier source ou 'raw_text'.")
            full = bool(ctx.options.get("full", False))
            extractor = extract.extract_video_dir_text if ctx.source.is_dir() else extract.extract_video_text
            raw = extractor(ctx.source, full=full)
        return render_template(profile, "video", {"raw_text": raw})

    return render_video


def _make_render_audio(profile: str) -> Callable[[RenderContext], str]:
    def render_audio(ctx: RenderContext) -> str:
        auto: dict[str, Any] = {}
        if ctx.source is not None:
            auto = extract.extract_album(ctx.source)
        context = _merge(auto, ctx.data)
        context.setdefault("tracklist", [])
        context.setdefault("total_size", 0)
        context.setdefault("total_size_dec", formats.human_size_dec(context["total_size"]))
        if "playing_time" not in context:
            total_dur = sum(t.get("duration", 0) for t in context["tracklist"])
            context["playing_time"] = formats.mmss(total_dur)
        context["name_width"] = ctx.options.get("name_width", 57)
        return render_template(profile, "audio", context)

    return render_audio


def _make_render_scan(profile: str, category: str) -> Callable[[RenderContext], str]:
    defaults = _SCAN_DEFAULTS.get(category, {})

    def render_scan(ctx: RenderContext) -> str:
        auto = extract.scan_files(ctx.source) if ctx.source is not None else {}
        context = _merge(auto, ctx.data)
        for key, value in defaults.items():
            context.setdefault(key, value)
        return render_template(profile, category, context)

    return render_scan


def _make_validator(category: str, schema: dict[str, Any]) -> Callable[[RenderContext, str], list[str]]:
    def validate(ctx: RenderContext, _nfo: str) -> list[str]:
        value = rules_engine.validate_and_get(ctx.data, schema)  # leve si absent/non conforme
        warnings = rules_engine.warnings(value, schema)
        capture_values = rules_engine.captures(value, schema)

        # Le croisement avec les metadonnees reelles du fichier n'existe
        # aujourd'hui que pour la video (seule extraction structuree
        # disponible, cf. extract.extract_video_metadata) : pas une
        # restriction du moteur de regles, juste l'etat actuel de l'extraction.
        if category != "video":
            return warnings

        # `video_metadata` : metadonnees deja extraites par l'appelant (ex.
        # extraction MediaInfo cote navigateur via WebAssembly, sans upload
        # du fichier -- voir frontend/src/lib/clientMediaInfo.ts), a utiliser
        # de preference a une re-extraction depuis `ctx.source` puisqu'il n'y
        # a alors aucun fichier reel cote serveur. Meme forme que
        # `extract.extract_video_metadata`/`extract_video_dir_metadata`
        # (liste de dicts, ou un seul dict pour un fichier).
        provided = ctx.data.get("video_metadata")
        if provided is not None:
            metas = provided if isinstance(provided, list) else [provided]
        elif ctx.source is not None:
            try:
                metas = (
                    extract.extract_video_dir_metadata(ctx.source)
                    if ctx.source.is_dir()
                    else [extract.extract_video_metadata(ctx.source)]
                )
            except Exception:
                metas = []
        else:
            metas = []
        for meta in metas:
            prefix = f"[{meta['name']}] " if "name" in meta else ""
            meta_warnings = rules_engine.cross_check_warnings(
                capture_values, meta, schema
            ) + rules_engine.track_language_warnings(meta, schema, capture_values)
            warnings.extend(f"{prefix}{w}" for w in meta_warnings)
        return warnings

    return validate


def _make_filename_rule(schema: dict[str, Any]) -> Callable[[RenderContext], str]:
    def filename_rule(ctx: RenderContext) -> str:
        return rules_engine.render_filename(ctx.data, schema)

    return filename_rule


def _make_name_proposal_rule(
    config: dict[str, Any],
) -> Callable[..., name_proposal_engine.NameProposal]:
    def propose(
        filenames: list[str], title_hints: list[str | None] | None = None
    ) -> name_proposal_engine.NameProposal:
        return name_proposal_engine.propose_video_release_name(filenames, config, title_hints)

    return propose


def register_declarative_profile(profile: str, rules: dict[str, Any]) -> None:
    """Enregistre un profil entierement pilote par `rules` (contenu d'un
    `rules.json`) : un renderer par categorie fixe (toujours, pour pouvoir
    generer un NFO), et un validateur / une regle de nommage uniquement pour
    les categories qui en declarent un dans `rules` (`requires_field`,
    `filename_template`). `rules` est valide contre le schema formel avant
    tout enregistrement (echec rapide sur un rules.json malforme, qu'il
    s'agisse du profil livre ou d'un profil utilisateur)."""
    rules_engine.validate_rules_document(rules)

    register(profile, "video")(_make_render_video(profile))
    register(profile, "audio")(_make_render_audio(profile))
    register(profile, "game")(_make_render_scan(profile, "game"))
    register(profile, "ebook")(_make_render_scan(profile, "ebook"))
    register(profile, "print3d")(_make_render_scan(profile, "print3d"))

    for category, schema in rules.items():
        if category not in CATEGORIES:
            continue  # cle inconnue dans rules.json : ignoree (pas bloquant)
        if schema.get("requires_field"):
            register_validator(profile, category)(_make_validator(category, schema))
        if schema.get("filename_template"):
            register_filename(profile, category)(_make_filename_rule(schema))
        if category == "video" and schema.get("name_proposal"):
            register_name_proposal(profile, category)(_make_name_proposal_rule(schema["name_proposal"]))
