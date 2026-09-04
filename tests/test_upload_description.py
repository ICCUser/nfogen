"""Tests de nfogen.upload_description (AUTOMATION.md, sous-projet 5) :
rend le gabarit BBCode de description d'upload -- meme moteur Jinja2 que
les .nfo (render.render_template), mecanisme parallele au systeme
categorie/registre (la description n'est pas un type de media)."""
from __future__ import annotations

from nfogen.upload_description import render_upload_description

FULL_CONTEXT = {
    "title": "Inception",
    "overview": "Dom Cobb est un voleur experimente...",
    "poster_url": "https://image.tmdb.org/t/p/w500/poster.jpg",
    "genres": ["Science-Fiction", "Action"],
    "directors": ["Christopher Nolan"],
    "cast": ["Leonardo DiCaprio", "Joseph Gordon-Levitt"],
    "resolution": "2160",
    "source": "BluRay",
    "video_codec": "hevc",
    "audio_languages": ["French", "English"],
}


def test_renders_synopsis_and_poster():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "Dom Cobb est un voleur experimente" in out
    assert "https://image.tmdb.org/t/p/w500/poster.jpg" in out


def test_renders_genres_directors_cast():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "Science-Fiction" in out
    assert "Christopher Nolan" in out
    assert "Leonardo DiCaprio" in out


def test_renders_without_optional_fields():
    """Overview/poster/genres/directors/cast peuvent tous manquer (ex.
    Radarr/Sonarr n'ont rien trouve) -- le gabarit ne doit jamais planter,
    juste omettre les sections vides."""
    minimal = {
        "title": "Inception", "overview": "", "poster_url": None,
        "genres": [], "directors": [], "cast": [],
        "resolution": "2160", "source": "BluRay", "video_codec": "hevc",
        "audio_languages": [],
    }
    out = render_upload_description("c411", minimal)
    assert "Inception" in out
    assert len(out) >= 20  # respecte le minimum de 20 caracteres exige par l'API C411


def test_output_meets_c411_minimum_length():
    """L'API C411 exige description >= 20 caracteres (voir doc, champs
    requis) -- verifie que meme le cas minimal du test precedent le
    respecte, contrat explicite plutot qu'implicite."""
    minimal = {
        "title": "X", "overview": "", "poster_url": None,
        "genres": [], "directors": [], "cast": [],
        "resolution": "1080", "source": "WEB", "video_codec": "x264",
        "audio_languages": [],
    }
    out = render_upload_description("c411", minimal)
    assert len(out) >= 20
