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
    "subtitle_languages": ["French"],
    "video_bit_rate_kbps": 12000,
    "release_date": "2010-07-15",
    "runtime_display": "2h28min",
    "distributor": "Warner Bros.",
    "certification": "PG-13",
    "release_name": "Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM",
    "team": "TEAM",
    "file_count": 1,
    "total_size_bytes": 21474836480,
}

# Champs TOUJOURS presents en conditions reelles (calcules par
# send_to_tracker, jamais optionnels contrairement a overview/genres/...
# qui peuvent legitimement manquer si Radarr/Sonarr n'ont rien trouve) --
# tout context de test doit les inclure, meme minimal.
_ALWAYS_PRESENT = {
    "release_name": "X.2020.1080p.BluRay-TEAM", "file_count": 1, "total_size_bytes": 1_000_000_000,
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


def test_renders_release_date_runtime_certification_distributor():
    """Champs confirmes disponibles en conditions reelles le 2026-09-06
    (retour utilisateur, GET /api/v3/movie et /api/v3/series reels)."""
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "2010-07-15" in out
    assert "2h28min" in out
    assert "PG-13" in out
    assert "Warner Bros." in out


def test_renders_audio_and_subtitle_languages_and_bitrate():
    """`audio_languages` restait cable en dur a [] jusqu'ici (retour
    utilisateur, 2026-09-06) -- verifie que le rendu utilise bien la
    liste fournie, plus le debit video et les sous-titres."""
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "French, English" in out
    assert "12000 kb/s" in out
    assert "French" in out  # sous-titres


def test_renders_release_name_team_file_count_and_size():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM" in out
    assert "TEAM" in out
    assert "1" in out  # nombre de fichiers
    assert "20.0" in out or "20 " in out  # 21474836480 octets ~= 20 GiB (human_bin)


def test_renders_without_optional_fields():
    """Overview/poster/genres/directors/cast/date/duree/etc. peuvent tous
    manquer (ex. Radarr/Sonarr n'ont rien trouve) -- le gabarit ne doit
    jamais planter, juste omettre les sections vides. `release_name`/
    `file_count`/`total_size_bytes` restent toujours fournis (voir
    _ALWAYS_PRESENT), ce ne sont jamais des absences legitimes."""
    minimal = {
        **_ALWAYS_PRESENT,
        "title": "Inception", "overview": "", "poster_url": None,
        "genres": [], "directors": [], "cast": [],
        "resolution": "2160", "source": "BluRay", "video_codec": "hevc",
        "audio_languages": [], "subtitle_languages": [], "video_bit_rate_kbps": None,
        "release_date": None, "runtime_display": None,
        "distributor": None, "certification": None, "team": None,
    }
    out = render_upload_description("c411", minimal)
    assert "Inception" in out
    assert len(out) >= 20  # respecte le minimum de 20 caracteres exige par l'API C411


def test_output_meets_c411_minimum_length():
    """L'API C411 exige description >= 20 caracteres (voir doc, champs
    requis) -- verifie que meme le cas minimal du test precedent le
    respecte, contrat explicite plutot qu'implicite."""
    minimal = {
        **_ALWAYS_PRESENT,
        "title": "X", "overview": "", "poster_url": None,
        "genres": [], "directors": [], "cast": [],
        "resolution": "1080", "source": "WEB", "video_codec": "x264",
        "audio_languages": [], "subtitle_languages": [], "video_bit_rate_kbps": None,
        "release_date": None, "runtime_display": None,
        "distributor": None, "certification": None, "team": None,
    }
    out = render_upload_description("c411", minimal)
    assert len(out) >= 20
