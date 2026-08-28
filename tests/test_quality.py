"""Tests de nfogen.quality (extraction/comparaison qualite-langue).

Les cas de la chaine de priorite/langue/coexistence sont bases directement
sur la politique anti-doublon C411 collee dans GAPSCAN.md (regles reelles du
site, pas une invention) : Chaine de priorite (langue > resolution > source >
type audio > codec video > canaux audio > HDR), coexistences VFF/VFQ,
HDR/DV separes, lossy/lossless.
"""
from __future__ import annotations

from nfogen.quality import (
    build_quality,
    is_language_gap,
    is_quality_upgrade,
    language_groups_from_names,
    parse_release_name,
)


def test_parse_release_name_full():
    q = parse_release_name("Matrix.1999.MULTI.VFF.2160p.BluRay.4KLight.HDR.DTS.5.1.x265-QTZ")
    assert q.resolution == 2160
    assert q.source == "BLURAY"
    assert q.codec == "X265"
    assert q.languages == ["VFF"]
    assert q.multi is True


def test_parse_release_name_no_language_is_not_an_error():
    q = parse_release_name("Some.Clip.2020.1080p.WEB.H264-TEAM")
    assert q.languages == []
    assert q.resolution == 1080


def test_source_rank_orders_remux_above_webrip():
    remux = parse_release_name("Film.2020.MULTI.VFF.1080p.REMUX.DTS.5.1.x264-TEAM")
    webrip = parse_release_name("Film.2020.MULTI.VFF.1080p.WEBRip.AAC.5.1.x264-TEAM")
    assert remux.source_rank < webrip.source_rank  # rang plus bas = meilleur


def test_source_rank_treats_webdl_webrip_and_web_as_equivalent():
    """C411 normalise WEBDL/WEB-DL/WEBRip vers le meme tag 'WEB' a l'upload
    (voir rules.json -> video -> name_proposal -> source_aliases) -- les
    distinguer ici comparerait a tort une release locale scene ('WEB-DL') a
    une release C411 ('WEB') comme si l'une valait mieux que l'autre.
    Incident reel : Van Wilder 3 (2009) classe a tort "quality_gap" alors
    qu'une release C411 equivalente existait deja (2026-08-28)."""
    webdl = parse_release_name("Film.2020.MULTI.VFF.1080p.WEB-DL.AC3.5.1.x264-TEAM")
    web = parse_release_name("Film.2020.MULTI.VFF.1080p.WEB.AC3.5.1.x264-TEAM")
    webrip = parse_release_name("Film.2020.MULTI.VFF.1080p.WEBRip.AC3.5.1.x264-TEAM")
    assert webdl.source_rank == web.source_rank == webrip.source_rank


def test_is_quality_upgrade_false_for_local_webdl_vs_remote_web_equivalent_release():
    """Cas reel (Van Wilder 3, 2026-08-28) : ta version scene 'WEB-DL' et la
    release C411 'WEB' designent la meme source -- aucune des deux ne doit
    etre jugee "meilleure" que l'autre."""
    local = parse_release_name("Van.Wilder.Freshman.Year.2009.MULTI.1080p.WEB-DL.H264.AC3-LCDS")
    remote = parse_release_name(
        "Van.Wilder.3.La.Premiere.Annee.De.Fac.2009.MULTI.VFF.1080p.WEB.AC3.2.0.H264-LCDS"
    )
    assert is_quality_upgrade(local, remote) is False


def test_is_quality_upgrade_by_source():
    local = parse_release_name("Film.2020.MULTI.VFF.1080p.REMUX.DTS.5.1.x264-TEAM")
    remote = parse_release_name("Film.2020.MULTI.VFF.1080p.WEBRip.AAC.5.1.x264-TEAM")
    assert is_quality_upgrade(local, remote) is True
    assert is_quality_upgrade(remote, local) is False


def test_is_quality_upgrade_by_resolution_when_source_unknown():
    local = parse_release_name("Film.2020.MULTI.VFF.2160p.x264-TEAM")
    remote = parse_release_name("Film.2020.MULTI.VFF.1080p.x264-TEAM")
    assert is_quality_upgrade(local, remote) is True


def test_is_quality_upgrade_false_when_nothing_comparable():
    local = parse_release_name("Film.2020.MULTI.VFF.x264-TEAM")
    remote = parse_release_name("Film.2020.MULTI.VFF.x265-AUTRE")
    assert is_quality_upgrade(local, remote) is False


def test_is_language_gap_false_when_remote_has_better_language():
    """VFF (piste FR reelle) est un rang superieur a VOSTFR (sous-titres
    seuls) dans la hierarchie C411 : une release VFF sur C411 couvre deja
    quelqu'un qui n'a qu'un VOSTFR local -- pas un gap legitime a uploader.
    (Remplace l'ancienne hypothese par defaut d'avant la vraie regle :
    "VOSTFR distinct" sans notion de hierarchie. Le cas inverse -- LOCAL en
    VFF, C411 en VOSTFR seul -- reste un gap, cf.
    `test_single_track_variant_not_covered_by_vostfr_only` plus bas.)"""
    local = parse_release_name("Film.2020.VOSTFR.1080p.WEB.x264-TEAM")
    remote = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    assert is_language_gap(local, remote) is False


def test_is_language_gap_false_when_no_local_language():
    local = parse_release_name("Film.2020.1080p.WEB.x264-TEAM")
    remote = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    assert is_language_gap(local, remote) is False


def test_language_groups_from_names_maps_generic_names():
    assert language_groups_from_names(["French", "English"]) == {"VF", "VO"}


def test_language_groups_from_names_keeps_unknown():
    assert language_groups_from_names(["Klingon"]) == {"KLINGON"}


def test_build_quality_prefers_parseable_release_name():
    q = build_quality(
        "Film.2020.VFQ.1080p.BluRay.x264-TEAM",
        fallback_resolution=720,
        fallback_language_names=["English"],
    )
    assert q.resolution == 1080  # vient du release_name, pas du fallback
    assert q.languages == ["VFQ"]  # langue trouvee dans le nom : le fallback est ignore


def test_build_quality_falls_back_to_structured_fields():
    q = build_quality(
        None, fallback_resolution=1080, fallback_source="webdl", fallback_language_names=["French"]
    )
    assert q.resolution == 1080
    assert q.source == "WEBDL"
    assert q.languages == ["VF"]


# --------------------------------------------------------------------------- #
# Rang de langue (politique C411, section "Priorite des langues") :
# MULTI.VF2 (VO+VFF+VFQ) > VF2 (VFF+VFQ sans VO) > {VFF,VFQ,VFI,VOF,
# TRUEFRENCH} (coexistence, aucune ne supplante les autres) > VOSTFR > rien.
# --------------------------------------------------------------------------- #
def test_language_tier_multi_vf2_is_highest():
    multi_vf2 = parse_release_name("Severance.S01.MULTI.VF2.1080p.WEB.EAC3.5.1.H264-FW")
    vf2 = parse_release_name("Severance.S01.VF2.1080p.WEB.EAC3.5.1.H264-FW")
    assert multi_vf2.language_tier > vf2.language_tier


def test_language_tier_vf2_above_single_track_variants():
    vf2 = parse_release_name("Film.2020.VF2.1080p.WEB.x264-TEAM")
    vff = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    assert vf2.language_tier > vff.language_tier


def test_language_tier_single_track_variants_are_equal_rank():
    """VFF/VFQ/VFI/VOF/TRUEFRENCH : coexistence, aucune ne prime sur les
    autres (meme rang) -- cf. politique C411."""
    vff = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    vfq = parse_release_name("Film.2020.VFQ.1080p.WEB.x264-TEAM")
    truefrench = parse_release_name("Film.2020.TRUEFRENCH.1080p.WEB.x264-TEAM")
    assert vff.language_tier == vfq.language_tier == truefrench.language_tier


def test_language_tier_vostfr_below_single_track_french():
    vostfr = parse_release_name("Film.2020.VOSTFR.1080p.WEB.x264-TEAM")
    vff = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    assert vostfr.language_tier < vff.language_tier


def test_vff_and_vfq_coexist_neither_covers_the_other():
    """C'est le coeur de la regle de coexistence : avoir VFF localement
    n'est PAS couvert par une release C411 en VFQ seul (et inversement) --
    ce sont deux uploads legitimement distincts, pas des doublons."""
    local_vff = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    remote_vfq = parse_release_name("Film.2020.VFQ.1080p.WEB.x264-TEAM")
    assert is_language_gap(local_vff, remote_vfq) is True

    local_vfq = parse_release_name("Film.2020.VFQ.1080p.WEB.x264-TEAM")
    remote_vff = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    assert is_language_gap(local_vfq, remote_vff) is True


def test_vf2_covers_a_single_track_variant():
    """VF2 contient de fait les pistes VFF+VFQ : une release VF2 sur C411
    couvre deja quelqu'un qui n'a qu'une VFF locale."""
    local_vff = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    remote_vf2 = parse_release_name("Film.2020.VF2.1080p.WEB.x264-TEAM")
    assert is_language_gap(local_vff, remote_vf2) is False


def test_single_track_variant_not_covered_by_vostfr_only():
    local_vff = parse_release_name("Film.2020.VFF.1080p.WEB.x264-TEAM")
    remote_vostfr = parse_release_name("Film.2020.VOSTFR.1080p.WEB.x264-TEAM")
    assert is_language_gap(local_vff, remote_vostfr) is True


def test_generic_fallback_language_matches_any_single_track_variant():
    """Sonarr/Radarr ne distinguent pas VFF/VFQ (juste 'French' generique) :
    ce marqueur generique ne doit pas produire un faux gap contre N'IMPORTE
    QUELLE variante FR precise deja presente sur C411."""
    local = build_quality(None, fallback_language_names=["French"])
    remote_vfq = parse_release_name("Film.2020.VFQ.1080p.WEB.x264-TEAM")
    assert is_language_gap(local, remote_vfq) is False


# --------------------------------------------------------------------------- #
# Chaine de priorite qualite (hors langue, geree a part ci-dessus) :
# resolution > source (REMUX/BDMV/ISO au sommet) > type audio (lossless >
# lossy) > codec video > canaux audio > HDR. Exemples tires de GAPSCAN.md.
# --------------------------------------------------------------------------- #
def test_remux_bdmv_iso_are_equally_pure_above_an_encode():
    """WALL.E.2008... exemples de GAPSCAN.md : BDMV/ISO/REMUX sont les 3
    structures 'sans reencodage' du profil Home Cinema Pure, a egalite."""
    bdmv = parse_release_name("WALL.E.2008.MULTI.VFF.1080p.BluRay.BDMV.DTS.5.1.AVC-NOTAG")
    iso = parse_release_name("WALL.E.2008.MULTI.VFF.1080p.BluRay.ISO.DTS.5.1.AVC-NOTAG")
    encoded = parse_release_name("WALL.E.2008.MULTI.VFF.1080p.BluRay.DTS.5.1.x264-NOTAG")
    assert is_quality_upgrade(bdmv, encoded) is True
    assert is_quality_upgrade(iso, encoded) is True
    assert is_quality_upgrade(bdmv, iso) is False
    assert is_quality_upgrade(iso, bdmv) is False


def test_lossless_audio_beats_lossy_at_equal_resolution_and_source():
    lossless = parse_release_name("Film.2020.MULTI.VFF.1080p.BluRay.TrueHD.5.1.x264-TEAM")
    lossy = parse_release_name("Film.2020.MULTI.VFF.1080p.BluRay.EAC3.5.1.x264-TEAM")
    assert is_quality_upgrade(lossless, lossy) is True
    assert is_quality_upgrade(lossy, lossless) is False


def test_more_audio_channels_wins_when_everything_else_equal():
    seven_one = parse_release_name("Film.2020.MULTI.VFF.1080p.BluRay.EAC3.7.1.x264-TEAM")
    five_one = parse_release_name("Film.2020.MULTI.VFF.1080p.BluRay.EAC3.5.1.x264-TEAM")
    assert is_quality_upgrade(seven_one, five_one) is True


def test_resolution_outranks_source_per_c411_priority_chain():
    """La chaine officielle place la resolution AVANT la source : un 2160p
    WEBRip doit l'emporter sur un 1080p REMUX."""
    higher_res = parse_release_name("Film.2020.MULTI.VFF.2160p.WEBRip.EAC3.5.1.x265-TEAM")
    lower_res_remux = parse_release_name("Film.2020.MULTI.VFF.1080p.REMUX.DTS.5.1.x264-TEAM")
    assert is_quality_upgrade(higher_res, lower_res_remux) is True


def test_hdr_dv_combined_beats_hdr_alone():
    """Exemple Squid.Game (GAPSCAN.md) : DV.HDR10 (combine) prefere a un
    HDR10 seul, a caracteristiques sinon identiques."""
    dv_hdr = parse_release_name(
        "Squid.Game.2021.S01.MULTi.VFF.2160p.WEBRip.4KLight.DV.HDR10.EAC3.Atmos.5.1.x265-ASKO"
    )
    hdr_only = parse_release_name(
        "Squid.Game.2021.S01.MULTi.VFF.2160p.WEBRip.4KLight.HDR10.EAC3.Atmos.5.1.x265-AUTRE"
    )
    assert is_quality_upgrade(dv_hdr, hdr_only) is True
    assert is_quality_upgrade(hdr_only, dv_hdr) is False
