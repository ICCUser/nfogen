r"""Tests de `rules.captures()` sur le groupe nomme "language" (AUTOMATION.md,
sous-projet 5) : incident reel (moderation C411, 2026-09-10 -- pack Lucifer
S05) : le parametre "Langue" envoye a l'upload etait "Francais (VFF/
TrueFrench)" au lieu de "Multi (Francais inclus)" pour une release MULTI --
la regex du token "language" excluait le prefixe "MULTI." du groupe capture
(non-capturing group `(?:MULTI\.)?`), donc `capture_values["language"]`
valait toujours juste "VFF", jamais "MULTI.VFF" (seule cle connue de
`language_values` pour la valeur "Multi" cote C411, voir
c411_upload_options.py:build_options)."""
from __future__ import annotations

from nfogen import rules as rules_engine

SCHEMA = {
    "tokens": [
        {
            "name": "language",
            "pattern": r"\.(?P<language>(?:MULTI\.)?(?:VFF|VFQ|VF2|VFI|VOF|VO|VOSTFR|FRENCH|TRUEFRENCH))\.",
        },
    ]
}


def test_captures_language_includes_multi_prefix_when_present():
    release_name = "Lucifer.S05.MULTI.VFF.1080p.WEB.AAC.2.0.H265-Frosties"
    assert rules_engine.captures(release_name, SCHEMA) == {"language": "MULTI.VFF"}


def test_captures_language_without_multi_stays_plain():
    release_name = "Joker.2015.VOSTFR.1080p.BluRay.AC3.5.1.x264-TEAM"
    assert rules_engine.captures(release_name, SCHEMA) == {"language": "VOSTFR"}


def test_real_c411_profile_language_capture_includes_multi_prefix():
    """Bout-en-bout contre le VRAI profil livre (nfogen/profiles/c411/rules.json)
    -- pas seulement un schema de test isole -- pour prouver que le regex
    reellement utilise par send_to_tracker() (voir upload_prep.py:680,
    `rules_captures(release_name, schema)`) est corrige, pas juste un
    schema hypothetique."""
    from nfogen.profile_store import read_profile

    schema = read_profile("c411")["rules"]["video"]
    release_name = "Lucifer.S05.MULTI.VFF.1080p.WEB.AAC.2.0.H265-Frosties"
    assert rules_engine.captures(release_name, schema)["language"] == "MULTI.VFF"
