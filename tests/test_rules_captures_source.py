r"""Tests de `rules.captures()` sur le groupe nomme "source" (rules.json ->
video -> tokens) : ce regex sert a RE-EXTRAIRE/VALIDER le champ `source`
depuis un release_name DEJA CONFIRME (voir c411_upload_options.build_options),
un mecanisme distinct de `_detect_via_aliases` (name_proposal.py) qui
construit le nom depuis un nom de fichier source. Audit C411 2026-09-13 :
ce regex n'incluait pas "WEBRip" (le nom entier restait capture par
l'alternative "WEB", moins specifique) -- corrige ici (point 1/4)."""
from __future__ import annotations

from nfogen import rules as rules_engine

SCHEMA = {
    "tokens": [
        {
            "name": "source",
            "pattern": r"\.(?P<source>BluRay\.REMUX|BluRay|BDRip|WEBRip|WEB\.[A-Za-z]+|WEB|HDTV|DVDRip)\.",
        },
    ]
}


def test_captures_source_webrip_stays_distinct_from_web():
    release_name = "Movie.2020.1080p.WEBRip.x265-TEAM"
    assert rules_engine.captures(release_name, SCHEMA) == {"source": "WEBRip"}


def test_captures_source_plain_webdl_still_captured_as_web():
    release_name = "Movie.2020.1080p.WEB.x265-TEAM"
    assert rules_engine.captures(release_name, SCHEMA) == {"source": "WEB"}


def test_real_c411_profile_source_capture_webrip():
    """Bout-en-bout contre le VRAI profil livre (nfogen/profiles/c411/rules.json)."""
    from nfogen.profile_store import read_profile

    schema = read_profile("c411")["rules"]["video"]
    release_name = "Movie.2020.1080p.WEBRip.x265-TEAM"
    assert rules_engine.captures(release_name, schema)["source"] == "WEBRip"
