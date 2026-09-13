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
    "country": "United States of America",
    "creators": [],
    "tmdb_rating": 8.4,
    "imdb_url": "https://www.imdb.com/title/tt1375666/",
    "resolution": "2160",
    "source": "BluRay",
    "video_codec": "hevc",
    "audio_rows": [
        {"flag": "https://flagcdn.com/20x15/fr.png", "language": "Français",
         "channels": "5.1", "codec": "AC-3", "bit_rate_kbps": 448, "sampling_khz": 48.0},
    ],
    "subtitle_rows": [
        {"flag": "https://flagcdn.com/20x15/fr.png", "language": "Français",
         "format": "UTF-8", "type": "FORCÉ"},
    ],
    "video_bit_rate_kbps": 12000,
    "container": "MKV",
    "hdr_format": "Dolby Vision",
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


def test_renders_synopsis():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "Dom Cobb est un voleur experimente" in out


def test_renders_the_tmdb_poster_image():
    """Correction (2026-09-13) : le retrait du poster (ec11dbb) partait
    d'une lecture trop large du retour de moderation "L'hebergeur que tu
    utilises pour la banniere n'est pas accepte sur C411" -- a l'epoque,
    la description avait AUSSI 4 bannieres de section hebergees sur
    raw.githubusercontent.com (voir test_renders_plain_text_section_
    headers_no_images ci-dessous), et c'est CA que la moderation visait.
    Retour reel de l'utilisateur (2026-09-13, upload Lucifer S03 reussi) :
    "l'image de prez du media c'est l'image de tmdb [img]https://
    image.tmdb.org/...[/img] ca ca passe" -- image.tmdb.org est bien
    accepte par C411, seul raw.githubusercontent.com etait refuse."""
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "[img]https://image.tmdb.org/t/p/w500/poster.jpg[/img]" in out


def test_renders_genres_directors_cast():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "Science-Fiction" in out
    assert "Christopher Nolan" in out
    assert "Leonardo DiCaprio" in out


def test_renders_plain_text_section_headers_no_images():
    """Retour reel de moderation C411, 2026-09-13 : d'abord le poster
    TMDB, puis "enleve les bannieres, github n'est pas accepte non plus"
    -- les 4 bannieres de section (Informations/Synopsis/Details
    techniques/Telechargement) etaient des images hebergees sur
    raw.githubusercontent.com, meme probleme que le poster. Remplacees
    par du texte simple, plus AUCUNE image dans toute la description."""
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "raw.githubusercontent.com" not in out
    assert "[b][size=120]Informations[/size][/b]" in out
    assert "[b][size=120]Synopsis[/size][/b]" in out
    assert "[b][size=120]Détails techniques[/size][/b]" in out
    assert "[b][size=120]Téléchargement[/size][/b]" in out


def test_renders_country_creators_rating_imdb():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "United States of America" in out
    assert "8.4/10" in out
    assert "https://www.imdb.com/title/tt1375666/" in out


def test_renders_audio_and_subtitle_tables_with_flags():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "[table]" in out
    assert "flagcdn.com/20x15/fr.png" in out
    assert "5.1" in out and "AC-3" in out and "448 kb/s" in out and "48.0 kHz" in out
    assert "FORCÉ" in out


def test_renders_langue_s_bullet_from_audio_tracks():
    """Retour reel de moderation C411, 2026-09-13 : "Description
    incomplete -- la section 'Langue(s)' doit contenir la liste des
    pistes audio" -- manquait entierement de la liste "Details
    techniques", seul le tableau audio detaille listait les langues."""
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "[*]Langue(s) : Français" in out


def test_langue_s_bullet_joins_multiple_audio_languages():
    context = {
        **FULL_CONTEXT,
        "audio_rows": [
            {**FULL_CONTEXT["audio_rows"][0], "language": "Français"},
            {**FULL_CONTEXT["audio_rows"][0], "language": "Anglais"},
        ],
    }
    out = render_upload_description("c411", context)
    assert "[*]Langue(s) : Français, Anglais" in out


def test_no_langue_s_bullet_when_no_audio_tracks():
    context = {**FULL_CONTEXT, "audio_rows": []}
    out = render_upload_description("c411", context)
    assert "Langue(s)" not in out


def test_renders_subtitle_format_column():
    """Retour reel de moderation C411, 2026-09-12 (pack Lucifer S05) :
    "0/3 pistes conformes" -- le format de piste (SRT/ASS/PGS/Timed
    Text/...) manquait completement du tableau BBCode, en plus du Type."""
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "Format" in out
    assert "UTF-8" in out


def test_renders_container_and_hdr_format():
    """Retour utilisateur, 2026-09-07 -- template C411 perso avec
    {{CONTAINER}}/{{HDR}} : nfogen doit s'en inspirer."""
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "MKV" in out
    assert "Dolby Vision" in out


def test_renders_release_date_runtime_certification_distributor():
    """Champs confirmes disponibles en conditions reelles le 2026-09-06
    (retour utilisateur, GET /api/v3/movie et /api/v3/series reels)."""
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "2010-07-15" in out
    assert "2h28min" in out
    assert "PG-13" in out
    assert "Warner Bros." in out


def test_renders_release_name_team_file_count_and_size():
    out = render_upload_description("c411", FULL_CONTEXT)
    assert "Inception.2010.MULTI.VFF.2160p.BluRay.x265-TEAM" in out
    assert "TEAM" in out
    assert "1" in out  # nombre de fichiers
    assert "20.0" in out or "20 " in out  # 21474836480 octets ~= 20 GiB (human_bin)


def test_renders_without_optional_fields():
    """Overview/poster/genres/directors/cast/date/duree/etc. peuvent tous
    manquer (ex. Radarr/Sonarr n'ont rien trouve, ou cle TMDB non
    configuree) -- le gabarit ne doit jamais planter, juste omettre les
    sections vides. `release_name`/`file_count`/`total_size_bytes`/les 4
    bannieres restent toujours fournis (voir _ALWAYS_PRESENT), ce ne sont
    jamais des absences legitimes."""
    minimal = {
        **_ALWAYS_PRESENT,
        "title": "Inception", "overview": "", "poster_url": None,
        "genres": [], "directors": [], "cast": [], "country": None,
        "creators": [], "tmdb_rating": None, "imdb_url": None,
        "resolution": "2160", "source": "BluRay", "video_codec": "hevc",
        "audio_rows": [], "subtitle_rows": [], "video_bit_rate_kbps": None,
        "container": None, "hdr_format": None,
        "release_date": None, "runtime_display": None,
        "distributor": None, "certification": None, "team": None,
    }
    out = render_upload_description("c411", minimal)
    assert "Inception" in out
    assert "[table]" not in out
    assert "Conteneur" not in out
    assert len(out) >= 20  # respecte le minimum de 20 caracteres exige par l'API C411


def test_output_meets_c411_minimum_length():
    """L'API C411 exige description >= 20 caracteres (voir doc, champs
    requis) -- verifie que meme le cas minimal du test precedent le
    respecte, contrat explicite plutot qu'implicite."""
    minimal = {
        **_ALWAYS_PRESENT,
        "title": "X", "overview": "", "poster_url": None,
        "genres": [], "directors": [], "cast": [], "country": None,
        "creators": [], "tmdb_rating": None, "imdb_url": None,
        "resolution": "1080", "source": "WEB", "video_codec": "x264",
        "audio_rows": [], "subtitle_rows": [], "video_bit_rate_kbps": None,
        "container": None, "hdr_format": None,
        "release_date": None, "runtime_display": None,
        "distributor": None, "certification": None, "team": None,
    }
    out = render_upload_description("c411", minimal)
    assert len(out) >= 20
