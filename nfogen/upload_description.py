"""Rendu de la description BBCode d'un upload (AUTOMATION.md, sous-projet
5) : meme moteur Jinja2 que les .nfo (`render.render_template`), mais
mecanisme PARALLELE au systeme categorie/registre -- une description n'est
pas un "type de media" comme video/audio/etc. (`declarative_profile.CATEGORIES`),
donc ce module ne passe jamais par `register`/`registry`, juste un rendu
direct."""
from __future__ import annotations

from typing import Any

from . import render


def render_upload_description(profile: str, context: dict[str, Any]) -> str:
    """Rend `profiles/<profile>/templates/upload_description.j2` avec le
    contexte fourni (titre, synopsis, affiche, genres, casting, infos
    qualite -- voir AUTOMATION.md pour la liste complete des cles
    attendues). Editable comme n'importe quel gabarit de profil."""
    return render.render_template(profile, "upload_description", context)
