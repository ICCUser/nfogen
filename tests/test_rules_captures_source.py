r"""Tests de `rules.captures()` sur le groupe nomme "source" (rules.json ->
video -> tokens) : ce regex sert a RE-EXTRAIRE/VALIDER le champ `source`
depuis un release_name DEJA CONFIRME (voir c411_upload_options.build_options),
un mecanisme distinct de `_detect_via_aliases` (name_proposal.py) qui
construit le nom depuis un nom de fichier source. Audit C411 2026-09-13 :
- point 1/4 : "WEBRip" n'etait pas capture (le nom entier retombait sur
  l'alternative "WEB", moins specifique).
- point 2/4 : "BluRay.BDMV" (ajoute a source_aliases par un audit
  precedent) et "BluRay.ISO" (nouveau, point 2) n'etaient/ne sont capturees
  qu'en partie ("BluRay" seul) si les alternatives composees ne sont pas
  placees AVANT leur prefixe "BluRay" dans le regex -- les alternatives
  regex Python sont essayees dans l'ordre ECRIT, contrairement a
  `_detect_via_aliases` qui trie explicitement par longueur de cle."""
from __future__ import annotations

from nfogen import rules as rules_engine

SCHEMA = {
    "tokens": [
        {
            "name": "source",
            "pattern": (
                r"\.(?P<source>UHD\.BluRay\.REMUX|UHD\.BluRay\.BDMV|UHD\.BluRay\.ISO"
                r"|BluRay\.REMUX|BluRay\.BDMV|BluRay\.ISO|BluRay|BDRip"
                r"|WEBRip|WEB\.[A-Za-z]+|WEB|HDTV|DVDRip)\."
            ),
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

def test_captures_source_bluray_bdmv_stays_composed_not_truncated_to_bluray():
    release_name = "Movie.2020.2160p.BluRay.BDMV.HEVC-TEAM"
    assert rules_engine.captures(release_name, SCHEMA) == {"source": "BluRay.BDMV"}


def test_captures_source_bluray_iso_stays_composed_not_truncated_to_bluray():
    release_name = "Movie.2020.2160p.BluRay.ISO.HEVC-TEAM"
    assert rules_engine.captures(release_name, SCHEMA) == {"source": "BluRay.ISO"}


def test_real_c411_profile_source_capture_bluray_bdmv():
    from nfogen.profile_store import read_profile

    schema = read_profile("c411")["rules"]["video"]
    release_name = "Movie.2020.2160p.BluRay.BDMV.HEVC-TEAM"
    assert rules_engine.captures(release_name, schema)["source"] == "BluRay.BDMV"


def test_real_c411_profile_source_capture_bluray_iso():
    from nfogen.profile_store import read_profile

    schema = read_profile("c411")["rules"]["video"]
    release_name = "Movie.2020.2160p.BluRay.ISO.HEVC-TEAM"
    assert rules_engine.captures(release_name, schema)["source"] == "BluRay.ISO"

def test_captures_source_uhd_remux_2160p_stays_composed():
    release_name = "Movie.2020.2160p.UHD.BluRay.REMUX.HEVC-TEAM"
    assert rules_engine.captures(release_name, SCHEMA) == {"source": "UHD.BluRay.REMUX"}


def test_captures_source_uhd_bdmv_2160p_stays_composed():
    release_name = "Movie.2020.2160p.UHD.BluRay.BDMV.HEVC-TEAM"
    assert rules_engine.captures(release_name, SCHEMA) == {"source": "UHD.BluRay.BDMV"}


def test_captures_source_uhd_iso_2160p_stays_composed():
    release_name = "Movie.2020.2160p.UHD.BluRay.ISO.HEVC-TEAM"
    assert rules_engine.captures(release_name, SCHEMA) == {"source": "UHD.BluRay.ISO"}


def test_captures_source_plain_bluray_2160p_without_uhd_prefix_stays_plain():
    release_name = "Movie.2020.2160p.BluRay.x265-TEAM"
    assert rules_engine.captures(release_name, SCHEMA) == {"source": "BluRay"}


def test_real_c411_profile_source_capture_uhd_remux():
    from nfogen.profile_store import read_profile

    schema = read_profile("c411")["rules"]["video"]
    release_name = "Movie.2020.2160p.UHD.BluRay.REMUX.HEVC-TEAM"
    assert rules_engine.captures(release_name, schema)["source"] == "UHD.BluRay.REMUX"

