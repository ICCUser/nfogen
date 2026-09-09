"""Tests de l'orchestration nommage -> mise en scene + torrent
(`nfogen/upload_prep.py`, AUTOMATION.md sous-projet 4)."""
from __future__ import annotations

import threading
from pathlib import Path as _Path
from unittest.mock import patch

import pytest

from nfogen import upload_history_store
from nfogen.cancellation import OperationCancelled
from nfogen.qbittorrent_client import QBittorrentError
from nfogen.tmdb_client import TMDBError, TMDBExtraDetails
from nfogen.upload_prep import (
    CommitResult,
    ProposedFile,
    SeasonPackRequest,
    SeasonPackSeasonFiles,
    _language_hint_from_audio_tracks,
    commit_upload,
    group_by_team,
    preview_upload,
    resolve_staging_config,
    send_to_tracker,
)
from nfogen.upload_prep import (
    _validate_known_source_paths as _real_validate_known_source_paths,
)
from nfogen.upload_prep import (
    validate_staged_path as _real_validate_staged_path,
)


@pytest.fixture(autouse=True)
def _allow_all_paths_by_default(monkeypatch):
    """Neutralise par defaut les deux controles ajoutes lors de l'audit
    securite du 2026-09-09 (source_path doit avoir ete vu par un scan
    GapScan connu ; staged_path/nfo_path/torrent_path doivent rester sous
    staging_dir) -- ce fichier teste le COMPORTEMENT FONCTIONNEL de
    preview_upload()/commit_upload()/send_to_tracker(), pas ces deux
    controles specifiquement, deja couverts par des tests dedies plus bas
    (voir test_commit_upload_rejects_unknown_source_path et consorts, qui
    reactivent la VRAIE fonction en la re-importants avant patch)."""
    monkeypatch.setattr("nfogen.upload_prep._validate_known_source_paths", lambda paths: None)
    monkeypatch.setattr("nfogen.upload_prep.validate_staged_path", lambda path: None)


def test_files_with_same_team_form_one_group():
    filenames = ["Show.S01E01.1080p.WEB.x264-TEAM.mkv", "Show.S01E02.1080p.WEB.x264-TEAM.mkv"]
    groups = group_by_team(filenames, [None, None])
    assert groups == [[0, 1]]


def test_files_with_different_teams_form_separate_groups():
    filenames = ["Show.S01E01.1080p.WEB.x264-TeamA.mkv", "Show.S01E02.1080p.WEB.x264-TeamB.mkv"]
    groups = group_by_team(filenames, [None, None])
    assert groups == [[0], [1]]


def test_hint_takes_priority_over_filename_for_grouping():
    # Le hint donne "FromHint", different du nom de fichier -- ne doit pas
    # se retrouver mélangé avec un fichier qui, lui, n'a que "FromFilename".
    filenames = [
        "Show.S01E01.1080p.WEB.x264-FromFilename.mkv",
        "Show.S01E02.1080p.WEB.x264-FromFilename.mkv",
    ]
    hints = ["Show S01E01 1080p WebDl x264 - FromHint", None]
    groups = group_by_team(filenames, hints)
    assert groups == [[0], [1]]


def test_files_with_no_detectable_team_form_their_own_group():
    filenames = ["random_clip_one.mkv", "random_clip_two.mkv"]
    groups = group_by_team(filenames, [None, None])
    assert groups == [[0, 1]]  # les deux "None" forment un seul groupe ensemble


def test_group_order_matches_first_appearance():
    filenames = [
        "Show.S01E01.1080p.WEB.x264-TeamB.mkv",
        "Show.S01E02.1080p.WEB.x264-TeamA.mkv",
        "Show.S01E03.1080p.WEB.x264-TeamB.mkv",
    ]
    groups = group_by_team(filenames, [None, None, None])
    assert groups == [[0, 2], [1]]


def test_empty_input_returns_no_groups():
    assert group_by_team([], []) == []


def _fake_metadata(**overrides):
    base = {
        "video_height": None, "video_width": None, "video_format": None,
        "video_bit_rate": None, "frame_rate": None,
        "audio_languages": [], "subtitle_languages": [], "general_title": None,
    }
    base.update(overrides)
    return base


def test_single_movie_file_proposes_a_name_and_matching_staged_file():
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(["/media/Kaamelott.2005.VFF.1080p.BluRay.AC3.x264-Dam.mkv"])
    assert len(proposals) == 1
    group = proposals[0]
    assert group.blocked is False
    assert group.release_name is not None
    assert group.release_name.startswith("Kaamelott")
    assert len(group.files) == 1
    assert group.files[0].source_path == "/media/Kaamelott.2005.VFF.1080p.BluRay.AC3.x264-Dam.mkv"
    assert group.files[0].staged_name == f"{group.release_name}.mkv"


def test_season_pack_same_team_produces_one_group_with_per_file_names():
    paths = [
        "/media/One.Piece.S01E01.MULTI.VFF.1080p.WEB.AC3.x264-NOTAG.mkv",
        "/media/One.Piece.S01E02.MULTI.VFF.1080p.WEB.AC3.x264-NOTAG.mkv",
    ]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    group = proposals[0]
    assert group.release_name is not None
    assert ".S01." in group.release_name  # identifiant de pack, pas par-episode
    assert len(group.files) == 2
    assert "S01E01" in group.files[0].staged_name
    assert "S01E02" in group.files[1].staged_name
    # Le nom de pack sert de prefixe coherent sur chaque fichier individuel.
    assert group.files[0].staged_name.startswith("One.Piece")


def test_multi_team_pack_splits_into_separate_groups():
    paths = [
        "/media/Show.S01E01.1080p.WEB.x264-TeamA.mkv",
        "/media/Show.S01E02.1080p.WEB.x264-TeamB.mkv",
    ]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 2
    release_names = {p.release_name for p in proposals}
    assert any(name and name.endswith("-TeamA") for name in release_names)
    assert any(name and name.endswith("-TeamB") for name in release_names)


def test_ambiguous_group_is_blocked_with_no_files():
    """Deux saisons differentes AVEC le meme tag d'equipe : group_by_team ne
    les separe pas (meme equipe), mais name_proposal refuse toujours ce cas
    (saisons incoherentes) -- le groupe est marque bloque plutot que de
    deviner laquelle utiliser."""
    paths = ["/media/Show.S01E01.1080p.WEB.x264-TEAM.mkv", "/media/Show.S02E01.1080p.WEB.x264-TEAM.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert proposals[0].blocked is True
    assert proposals[0].release_name is None
    assert proposals[0].files == []
    assert any("saisons" in w for w in proposals[0].warnings)


def test_extraction_failure_for_one_file_does_not_crash():
    def fake_extract(source):
        if "corrupt" in str(source):
            raise RuntimeError("libmediainfo: fichier illisible")
        return _fake_metadata()

    paths = ["/media/corrupt.S01E01.1080p.WEB.x264-TEAM.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", side_effect=fake_extract):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert any("illisible" in w.lower() or "métadonnées" in w.lower() for w in proposals[0].warnings)
    assert proposals[0].release_name is not None  # l'echec d'extraction n'empeche pas le nommage


def test_upscale_warning_surfaces_through_real_c411_validator():
    """Preuve du cablage complet : preview_upload() reutilise le VRAI
    validateur du profil C411 (cross_checks + upscale_checks), sans aucune
    logique dupliquee ici."""
    meta = _fake_metadata(
        video_height=1080, video_width=1920, video_bit_rate=1_500_000, frame_rate=24.0,
    )
    paths = ["/media/Movie.2020.VFF.1080p.BluRay.AC3.x264-TEAM.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=meta):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert any("upscale" in w.lower() for w in proposals[0].warnings)
    assert proposals[0].blocked is False  # avertissement, jamais bloquant


def test_name_with_no_detectable_codec_is_blocked_by_real_validator():
    """Le nom propose ne respecte pas la convention C411 (codec video
    obligatoire absent) -- le vrai validateur du profil le refuse, le
    groupe est bloque plutot que mis en scene avec un nom invalide."""
    paths = ["/media/nom_totalement_generique.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert proposals[0].blocked is True


def test_empty_local_paths_returns_empty_list():
    assert preview_upload([]) == []


def test_preview_upload_season_pack_produces_one_group_with_prefixed_staged_names():
    """Retour utilisateur, 2026-09-08 : pack multi-saisons -- un seul
    GroupProposal, staged_name prefixe par saison (S05/..., S06/...) pour
    que file_staging.stage_files() mette en scene la structure imbriquee
    attendue (aucun changement necessaire a stage_files() lui-meme)."""
    season_pack = SeasonPackRequest(
        title="Lucifer", team="Frosties", is_full_series=True,
        seasons=[
            SeasonPackSeasonFiles(season_number=5, local_paths=["/media/S05/ep1.mkv", "/media/S05/ep2.mkv"]),
            SeasonPackSeasonFiles(season_number=6, local_paths=["/media/S06/ep1.mkv"]),
        ],
    )
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload([], profile="c411", season_pack=season_pack)

    assert len(proposals) == 1
    group = proposals[0]
    assert group.release_name is not None
    assert "INTEGRALE" in group.release_name
    assert len(group.files) == 3
    assert group.files[0].staged_name == "S05/ep1.mkv"
    assert group.files[1].staged_name == "S05/ep2.mkv"
    assert group.files[2].staged_name == "S06/ep1.mkv"
    assert group.blocked is False


def test_preview_upload_season_pack_warns_when_season_pack_not_configured(monkeypatch):
    season_pack = SeasonPackRequest(
        title="Show", team="TEAM", is_full_series=False,
        seasons=[
            SeasonPackSeasonFiles(season_number=1, local_paths=["/media/S01/ep1.mkv"]),
            SeasonPackSeasonFiles(season_number=2, local_paths=["/media/S02/ep1.mkv"]),
        ],
    )
    # Profil sans video.name_proposal.season_pack declare -- comportement
    # degrade explicite, jamais une convention devinee.
    monkeypatch.setattr(
        "nfogen.upload_prep.read_profile",
        lambda profile: {"rules": {"video": {"name_proposal": {"template": "{title}.{identifier}-{team}"}}}},
    )
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload([], profile="c411", season_pack=season_pack)

    assert len(proposals) == 1
    assert proposals[0].release_name is None
    assert proposals[0].blocked is True


def test_preview_upload_season_pack_extraction_failure_is_a_soft_warning():
    season_pack = SeasonPackRequest(
        title="Lucifer", team="Frosties", is_full_series=True,
        seasons=[SeasonPackSeasonFiles(season_number=5, local_paths=["/media/S05/ep1.mkv"])],
    )
    with patch("nfogen.upload_prep.extract.extract_video_metadata", side_effect=Exception("boom")):
        proposals = preview_upload([], profile="c411", season_pack=season_pack)

    assert len(proposals) == 1
    assert proposals[0].release_name is not None  # illisible = avertissement, jamais bloquant
    assert any("Métadonnées illisibles" in w for w in proposals[0].warnings)


def test_preview_upload_title_override_replaces_filename_derived_title():
    """Cas reel signale par l'utilisateur (2026-08-28) : le titre Sonarr/
    Radarr ('A Guy And A Girl') ne correspond pas au titre officiel attendu
    par C411 ('Un Gars, Une Fille'). L'override s'applique au nom de pack
    ET au nom individuel de chaque fichier."""
    paths = [
        "/media/A.Guy.And.A.Girl.S02E01.1080p.WEB.AC3.x264-Valentin.mkv",
        "/media/A.Guy.And.A.Girl.S02E02.1080p.WEB.AC3.x264-Valentin.mkv",
    ]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=_fake_metadata()):
        proposals = preview_upload(paths, title_override="Un Gars, Une Fille")
    assert len(proposals) == 1
    group = proposals[0]
    assert group.release_name.startswith("Un.Gars.Une.Fille.")
    assert all(f.staged_name.startswith("Un.Gars.Une.Fille.") for f in group.files)


def _make_source(tmp_path, name: str, content: bytes = b"contenu de test") -> str:
    p = tmp_path / name
    p.write_bytes(content)
    return str(p)


def test_commit_single_file_stages_and_builds_torrent(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.extract.extract_video_text", lambda path: "General\nFormat : Matroska\n"
    )
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]

    result = commit_upload("Movie.2020.1080p.x264-TEAM", files)

    assert isinstance(result, CommitResult)
    assert result.staged_path == str(staging_dir / "Movie.2020.1080p.x264-TEAM.mkv")
    assert _Path(result.staged_path).is_file()
    assert result.torrent_path == str(staging_dir / "Movie.2020.1080p.x264-TEAM.torrent")
    assert _Path(result.torrent_path).is_file()
    assert result.nfo_path == str(staging_dir / "Movie.2020.1080p.x264-TEAM.nfo")
    assert "General" in _Path(result.nfo_path).read_text(encoding="utf-8")


def test_commit_multi_file_group_stages_into_a_folder(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.extract.extract_video_dir_text",
        lambda path: "General\nFormat : Matroska (pack)\n",
    )
    files = [
        ProposedFile(
            source_path=_make_source(tmp_path, "e01.mkv"),
            staged_name="Show.S01E01.1080p.WEB.x264-TEAM.mkv",
        ),
        ProposedFile(
            source_path=_make_source(tmp_path, "e02.mkv"),
            staged_name="Show.S01E02.1080p.WEB.x264-TEAM.mkv",
        ),
    ]

    result = commit_upload("Show.S01.1080p.WEB.x264-TEAM", files)

    pack_dir = staging_dir / "Show.S01.1080p.WEB.x264-TEAM"
    assert result.staged_path == str(pack_dir)
    assert (pack_dir / "Show.S01E01.1080p.WEB.x264-TEAM.mkv").is_file()
    assert (pack_dir / "Show.S01E02.1080p.WEB.x264-TEAM.mkv").is_file()
    assert _Path(result.torrent_path).is_file()
    # Un seul .nfo pour tout le pack, pas un par episode.
    assert result.nfo_path == str(staging_dir / "Show.S01.1080p.WEB.x264-TEAM.nfo")
    assert _Path(result.nfo_path).is_file()
    assert "pack" in _Path(result.nfo_path).read_text(encoding="utf-8")


def test_commit_without_staging_dir_configured_raises(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: None)
    with pytest.raises(ValueError, match="scène"):
        commit_upload("X", [ProposedFile(source_path="/x.mkv", staged_name="X.mkv")])


def _configure_staging(monkeypatch, staging_dir, extract_text="General\nFormat : Matroska\n"):
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )
    monkeypatch.setattr("nfogen.upload_prep.extract.extract_video_text", lambda path: extract_text)


def test_commit_reuses_an_already_staged_pack_without_recopying(tmp_path, monkeypatch):
    """Incident reel (2026-09-06) : une saison deja entierement mise en
    scene lors d'un essai precedent se faisait integralement re-copier
    depuis le NAS (montage reseau, hardlink impossible) a chaque nouvelle
    tentative de "Confirmer" -- retour utilisateur : "il me re telecharge
    les mkv". Chaque fichier de taille identique a sa source doit rester
    intact, meme sans savoir si le titre a deja ete traite."""
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    _configure_staging(
        monkeypatch, staging_dir, extract_text="General\nFormat : Matroska (pack)\n",
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.extract.extract_video_dir_text",
        lambda path: "General\nFormat : Matroska (pack)\n",
    )
    pack_dir = staging_dir / "Show.S01.1080p.WEB.x264-TEAM"
    pack_dir.mkdir()
    e01 = _make_source(tmp_path, "e01.mkv", b"a" * 100)
    e02 = _make_source(tmp_path, "e02.mkv", b"b" * 200)
    # Deja mis en scene lors d'un essai precedent, meme taille que la
    # source -- contenu volontairement DIFFERENT (marqueur) pour prouver
    # qu'il n'est jamais retouche.
    (pack_dir / "Show.S01E01.1080p.WEB.x264-TEAM.mkv").write_bytes(b"X" * 100)
    (pack_dir / "Show.S01E02.1080p.WEB.x264-TEAM.mkv").write_bytes(b"Y" * 200)
    files = [
        ProposedFile(source_path=e01, staged_name="Show.S01E01.1080p.WEB.x264-TEAM.mkv"),
        ProposedFile(source_path=e02, staged_name="Show.S01E02.1080p.WEB.x264-TEAM.mkv"),
    ]

    result = commit_upload("Show.S01.1080p.WEB.x264-TEAM", files)

    assert (pack_dir / "Show.S01E01.1080p.WEB.x264-TEAM.mkv").read_bytes() == b"X" * 100
    assert (pack_dir / "Show.S01E02.1080p.WEB.x264-TEAM.mkv").read_bytes() == b"Y" * 200
    assert result.staged_path == str(pack_dir)


def test_commit_regenerates_a_stale_unprocessed_staged_file(tmp_path, monkeypatch):
    """Incident reel signale par l'utilisateur (2026-09-06) : un fichier
    laisse par un essai precedent (jamais confirme/envoye avec succes)
    faisait planter "Confirmer" avec un OSError brut ('[Errno 17] File
    exists'). Un tel dechet, jamais enregistre dans l'historique, est
    considere sur comme regenerable -- toujours DEPUIS LA SOURCE LOCALE
    deja sur le NAS, jamais un nouveau telechargement."""
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    _configure_staging(monkeypatch, staging_dir)
    (staging_dir / "Movie.2020.1080p.x264-TEAM.mkv").write_bytes(b"dechet d'un essai precedent")
    source = _make_source(tmp_path, "source.mkv", b"contenu reel")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]

    result = commit_upload(
        "Movie.2020.1080p.x264-TEAM", files, media_type="movie", radarr_movie_id=42,
    )

    assert _Path(result.staged_path).read_bytes() == b"contenu reel"


def test_commit_raises_a_clear_error_when_target_exists_and_already_processed(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    _configure_staging(monkeypatch, staging_dir)
    (staging_dir / "Movie.2020.1080p.x264-TEAM.mkv").write_bytes(b"deja envoye, potentiellement en seed")
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]
    upload_history_store.record(
        upload_history_store.processed_key("movie", 42, None),
        kind="sent", release_name="Movie.2020.1080p.x264-TEAM",
    )

    with pytest.raises(FileExistsError, match="déjà été confirmé/envoyé"):
        commit_upload("Movie.2020.1080p.x264-TEAM", files, media_type="movie", radarr_movie_id=42)

    # Le fichier existant (potentiellement en seed) n'est jamais touche.
    staged = staging_dir / "Movie.2020.1080p.x264-TEAM.mkv"
    assert staged.read_bytes() == b"deja envoye, potentiellement en seed"


def test_commit_regenerates_a_stale_torrent_left_by_a_previous_attempt(tmp_path, monkeypatch):
    """Incident reel signale par l'utilisateur (2026-09-06) : refaire
    'Confirmer' pour un titre pas encore traite, alors que son .torrent
    existait deja (essai precedent), faisait planter la generation avec
    un message brut ('File exists') -- torf refuse nativement d'ecraser
    un .torrent existant (torf.WriteError), jamais intercepte jusqu'ici
    (contrairement au fichier mis en scene, deja protege)."""
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    _configure_staging(monkeypatch, staging_dir)
    (staging_dir / "Movie.2020.1080p.x264-TEAM.torrent").write_bytes(b"dechet d'un essai precedent")
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]

    result = commit_upload("Movie.2020.1080p.x264-TEAM", files, media_type="movie", radarr_movie_id=42)

    assert _Path(result.torrent_path).is_file()
    assert _Path(result.torrent_path).read_bytes() != b"dechet d'un essai precedent"


def test_commit_raises_a_clear_error_when_torrent_exists_and_already_processed(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    _configure_staging(monkeypatch, staging_dir)
    # Le fichier mis en scene correspond deja (meme taille) -- seul le
    # .torrent est un "dechet" existant ici, pour isoler ce chemin de code.
    source = _make_source(tmp_path, "source.mkv", b"contenu de test")
    (staging_dir / "Movie.2020.1080p.x264-TEAM.mkv").write_bytes(b"contenu de test")
    (staging_dir / "Movie.2020.1080p.x264-TEAM.torrent").write_bytes(b"deja envoye, potentiellement en seed")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]
    upload_history_store.record(
        upload_history_store.processed_key("movie", 42, None),
        kind="sent", release_name="Movie.2020.1080p.x264-TEAM",
    )

    with pytest.raises(FileExistsError, match="déjà été confirmé/envoyé"):
        commit_upload("Movie.2020.1080p.x264-TEAM", files, media_type="movie", radarr_movie_id=42)

    torrent_path = staging_dir / "Movie.2020.1080p.x264-TEAM.torrent"
    assert torrent_path.read_bytes() == b"deja envoye, potentiellement en seed"


def test_commit_without_identifiers_still_regenerates_a_stale_file(tmp_path, monkeypatch):
    """Sans identifiant Radarr/Sonarr (comportement historique, avant le
    sous-projet 8) : impossible de savoir si c'est deja traite -- traite
    comme "pas encore traite", donc regenerable (comportement le moins
    surprenant : ne bloque jamais un appelant qui n'a pas ces champs)."""
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    _configure_staging(monkeypatch, staging_dir)
    (staging_dir / "Movie.2020.1080p.x264-TEAM.mkv").write_bytes(b"dechet")
    source = _make_source(tmp_path, "source.mkv", b"reel")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]

    result = commit_upload("Movie.2020.1080p.x264-TEAM", files)

    assert _Path(result.staged_path).read_bytes() == b"reel"


def test_commit_without_announce_url_configured_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url", lambda profile: None
    )
    with pytest.raises(ValueError, match="annonce"):
        commit_upload("X", [ProposedFile(source_path="/x.mkv", staged_name="X.mkv")])


def test_commit_without_automation_extra_raises(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep._TORRENT_BUILDER_AVAILABLE", False)
    with pytest.raises(RuntimeError, match="automation"):
        commit_upload("X", [ProposedFile(source_path="/x.mkv", staged_name="X.mkv")])


# --------------------------------------------------------------------------- #
# resolve_staging_config / hooks on_progress/cancel_event (AUTOMATION.md,
# sous-projet 4c) : commit_upload s'execute en tache de fond, suivi et
# annulable -- voir commit_job_runner.py.
# --------------------------------------------------------------------------- #
def test_resolve_staging_config_returns_staging_dir_and_announce_url(monkeypatch):
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: "/staging"
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )
    assert resolve_staging_config("c411") == ("/staging", "https://c411.example/announce/abc123")


def test_resolve_staging_config_raises_without_staging_dir(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: None)
    with pytest.raises(ValueError, match="scène"):
        resolve_staging_config("c411")


def test_commit_upload_reports_progress_through_all_three_steps(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.extract.extract_video_text", lambda path: "General\nFormat : Matroska\n"
    )
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]
    calls: list[tuple[str, float]] = []

    commit_upload(
        "Movie.2020.1080p.x264-TEAM", files, on_progress=lambda step, pct: calls.append((step, pct))
    )

    steps_seen = [step for step, _ in calls]
    assert steps_seen[0] == "staging"
    assert "generating_nfo" in steps_seen
    assert steps_seen[-1] == "building_torrent"
    assert calls[-1][1] == 100.0  # 100% a la toute fin de la derniere etape


def test_commit_upload_without_hooks_behaves_exactly_as_before(tmp_path, monkeypatch):
    """Comportement 100% synchrone inchange quand on_progress/cancel_event
    sont omis -- meme scenario que
    test_commit_single_file_stages_and_builds_torrent, sans hooks."""
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.extract.extract_video_text", lambda path: "General\nFormat : Matroska\n"
    )
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]

    result = commit_upload("Movie.2020.1080p.x264-TEAM", files)

    assert isinstance(result, CommitResult)
    assert _Path(result.staged_path).is_file()


def test_commit_upload_sets_torrent_source_from_profile(tmp_path, monkeypatch):
    """Retour C411, 2026-09-07 : "le plus simple c'est de le generer
    correctement de ton cote, en precisant source=C411" -- voir
    tracker_profile.torrent_source() et torrent_builder.build_torrent()."""
    import torf

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.extract.extract_video_text", lambda path: "General\nFormat : Matroska\n"
    )
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]

    result = commit_upload("Movie.2020.1080p.x264-TEAM", files, profile="c411")

    reloaded = torf.Torrent.read(result.torrent_path)
    assert reloaded.source == "C411"


def test_commit_upload_propagates_cancellation(tmp_path, monkeypatch):
    """Force le repli COPIE (jamais hardlink, EXDEV simule -- meme
    technique que test_file_staging.py) : l'annulation y est verifiee des
    le premier bloc, contrairement au hardlink (instantane, aucun
    checkpoint) ou a un torrent a une seule piece (torf peut ne jamais
    consulter le callback pour un job qui se termine avant d'y arriver --
    verifie separement dans test_torrent_builder.py sur un job multi-pieces)."""
    import errno
    import os as os_module

    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker_announce_url",
        lambda profile: "https://c411.example/announce/abc123",
    )

    def fake_link(src, dst):
        raise OSError(errno.EXDEV, "Invalid cross-device link")

    monkeypatch.setattr(os_module, "link", fake_link)
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name="Movie.2020.1080p.x264-TEAM.mkv")]
    cancel_event = threading.Event()
    cancel_event.set()

    with pytest.raises(OperationCancelled):
        commit_upload("Movie.2020.1080p.x264-TEAM", files, cancel_event=cancel_event)


# --------------------------------------------------------------------------- #
# Indice de langue derive des VRAIES pistes audio du fichier (jamais du nom
# de fichier) : comble un ecart signale par l'utilisateur -- le nom de
# fichier peut ne porter aucun tag de langue alors que le fichier a bien des
# pistes FR/EN detectees par MediaInfo (donc connues de GapScan via Radarr,
# mais invisibles jusqu'ici du moteur de nommage). Attention explicite de
# l'utilisateur (2026-08-28) : plusieurs langues doivent produire un indice
# qui declenche le prefixe MULTI attendu par C411, pas juste une langue.
# --------------------------------------------------------------------------- #
_C411_AUDIO_LANGUAGE_CODES = {
    "fr": "FR", "fre": "FR", "fra": "FR", "french": "FR",
    "en": "EN", "eng": "EN", "english": "EN",
    "ja": "JA", "jpn": "JA", "japanese": "JA",
}


def test_language_hint_single_known_track():
    assert _language_hint_from_audio_tracks(["fre"], _C411_AUDIO_LANGUAGE_CODES) == "FR"


def test_language_hint_combines_two_tracks_for_multi():
    assert _language_hint_from_audio_tracks(["fre", "eng"], _C411_AUDIO_LANGUAGE_CODES) == "FR+EN"


def test_language_hint_deduplicates_repeated_language():
    assert _language_hint_from_audio_tracks(["fre", "fre"], _C411_AUDIO_LANGUAGE_CODES) == "FR"


def test_language_hint_ignores_unrecognized_codes():
    assert _language_hint_from_audio_tracks(["fre", "klingon"], _C411_AUDIO_LANGUAGE_CODES) == "FR"


def test_language_hint_empty_when_nothing_recognized():
    assert _language_hint_from_audio_tracks([], _C411_AUDIO_LANGUAGE_CODES) == ""
    assert _language_hint_from_audio_tracks(["klingon"], _C411_AUDIO_LANGUAGE_CODES) == ""


def test_language_hint_empty_when_profile_declares_no_codes():
    # Profil sans audio_language_codes declare : jamais d'indice devine.
    assert _language_hint_from_audio_tracks(["fre", "eng"], {}) == ""


def test_preview_upload_uses_real_audio_tracks_when_filename_has_no_language_tag():
    """Cas reel signale par l'utilisateur (2026-08-28) : nom de fichier sans
    tag de langue, mais deux pistes audio FR/EN reellement presentes dans le
    fichier -- doit produire MULTI.VFF, pas 'LANGINCONNU'."""
    meta = _fake_metadata(audio_languages=["fre", "eng"])
    paths = ["/media/That.Awkward.Moment.2014.1080p.BluRay.AC3.5.1.x264-LOST.mkv"]
    with patch("nfogen.upload_prep.extract.extract_video_metadata", return_value=meta):
        proposals = preview_upload(paths)
    assert len(proposals) == 1
    assert "MULTI.VFF" in proposals[0].release_name
    assert not any("langue" in w.lower() for w in proposals[0].warnings)


# --------------------------------------------------------------------------- #
# send_to_tracker (AUTOMATION.md, sous-projet 5) : cree/met a jour un
# BROUILLON C411 -- jamais une soumission reelle.
# --------------------------------------------------------------------------- #
def test_send_to_tracker_warns_when_tmdb_key_not_configured(tmp_path, monkeypatch):
    """Retour C411, 2026-09-07 : tous les elements de la presentation sont
    obligatoires -- sans cle TMDB, Pays/Createur(s)/Note/IMDB manqueront."""
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    _basic_send_to_tracker_mocks(monkeypatch)
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tmdb_api_key", lambda: None
    )

    result = send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", tmdb_id=603,
    )

    assert result.presentation_warning is not None
    assert "TMDB" in result.presentation_warning


def test_send_to_tracker_no_presentation_warning_when_tmdb_key_configured(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    _basic_send_to_tracker_mocks(monkeypatch)
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tmdb_api_key", lambda: "tmdb-secret"
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.TMDBClient",
        lambda *a, **k: type(
            "F", (), {
                "get_movie_extra": lambda self, tmdb_id: TMDBExtraDetails(country="France"),
                "close": lambda self: None,
            },
        )(),
    )

    result = send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", tmdb_id=603,
    )

    assert result.presentation_warning is None


def test_send_to_tracker_movie_creates_a_draft(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeRadarrClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_movie_details(self, movie_id):
            from nfogen.radarr_client import RadarrMovieDetails
            assert movie_id == 42
            return RadarrMovieDetails(overview="Synopsis test.", genres=["Action"])

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.RadarrClient", FakeRadarrClient)
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_radarr",
        lambda: ("http://radarr.local", "radarr-key"),
    )

    captured: dict = {}

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            captured["duplicates_checked"] = (tmdb_id, tmdb_type)
            return []

        def create_draft(self, **kwargs):
            captured["create_draft_kwargs"] = kwargs
            return {"id": 555, "url": "https://c411.org/user/drafts/555"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    result = send_to_tracker(
        release_name="Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", radarr_movie_id=42, tmdb_id=603,
    )

    assert result.draft_id == 555
    assert result.draft_url == "https://c411.org/user/drafts/555"
    assert result.duplicate_warning is None
    assert captured["duplicates_checked"] == (603, "movie")
    kwargs = captured["create_draft_kwargs"]
    assert kwargs["title"] == "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM"
    assert "Synopsis test." in kwargs["description"]
    assert kwargs["category_id"] == 1
    assert kwargs["subcategory_id"] == 6
    assert kwargs["options"] == {"1": [2], "2": 413}  # VFF (MULTI.VFF) + BluRay.HDLight


def test_send_to_tracker_description_includes_new_metadata_fields(tmp_path, monkeypatch):
    """Retour utilisateur, 2026-09-06 : `release_date`/`runtime`/
    `studio`/`certification` (confirmes disponibles via Radarr en
    conditions reelles) et `team`/`file_count`/`total_size_bytes`
    (deja connus a ce stade) doivent apparaitre dans la description --
    `audio_languages` restait meme cable en dur a [] jusqu'ici."""
    staged = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeRadarrClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_movie_details(self, movie_id):
            from nfogen.radarr_client import RadarrMovieDetails
            return RadarrMovieDetails(
                overview="Synopsis test.", release_date="2020-05-01",
                runtime_minutes=108, studio="Test Studio", certification="12",
            )

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.RadarrClient", FakeRadarrClient)
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_radarr",
        lambda: ("http://radarr.local", "radarr-key"),
    )

    captured: dict = {}

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def create_draft(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"id": 558, "url": "https://c411.org/user/drafts/558"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    send_to_tracker(
        release_name="Movie.2020.MULTI.VFF.1080p.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", radarr_movie_id=42,
    )

    description = captured["kwargs"]["description"]
    assert "2020-05-01" in description
    assert "1h48min" in description
    assert "Test Studio" in description
    assert "12" in description
    assert "TEAM" in description  # team, extrait du release_name
    assert "Movie.2020.MULTI.VFF.1080p.BluRay-TEAM" in description  # release_name
    assert "MKV" in description  # container, derive de l'extension du fichier mis en scene


def test_send_to_tracker_description_includes_hdr_format(tmp_path, monkeypatch):
    """Retour utilisateur, 2026-09-07 -- template C411 perso avec
    {{HDR}} : nfogen doit s'en inspirer."""
    staged = tmp_path / "Movie.2020.2160p.UHD.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.2160p.UHD.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.2160p.UHD.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.extract.extract_video_metadata",
        lambda path: {"container": "MKV", "hdr_format": "Dolby Vision"},
    )

    captured: dict = {}

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def create_draft(self, **kwargs):
            captured["kwargs"] = kwargs
            return {"id": 559, "url": "https://c411.org/user/drafts/559"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    send_to_tracker(
        release_name="Movie.2020.2160p.UHD.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie",
    )

    assert "Dolby Vision" in captured["kwargs"]["description"]


def test_send_to_tracker_records_history_on_success(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    staged = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeRadarrClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_movie_details(self, movie_id):
            from nfogen.radarr_client import RadarrMovieDetails
            return RadarrMovieDetails(overview="Synopsis test.", genres=["Action"])

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.RadarrClient", FakeRadarrClient)
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_radarr",
        lambda: ("http://radarr.local", "radarr-key"),
    )

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            return []

        def create_draft(self, **kwargs):
            return {"id": 555, "url": "https://c411.org/user/drafts/555"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    send_to_tracker(
        release_name="Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", radarr_movie_id=42, tmdb_id=603,
    )

    key = upload_history_store.processed_key("movie", 42, None)
    assert upload_history_store.is_processed(key)


def test_send_to_tracker_without_identifiers_does_not_record_history(tmp_path, monkeypatch):
    monkeypatch.setenv("NFOGEN_UPLOAD_HISTORY_FILE", str(tmp_path / "history.json"))
    staged = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            return []

        def create_draft(self, **kwargs):
            return {"id": 555, "url": "https://c411.org/user/drafts/555"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    send_to_tracker(
        release_name="Movie.2020.MULTI.VFF.1080p.BluRay.HDLight.AC3.x264-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411",  # aucun identifiant Radarr/Sonarr fourni
    )

    assert not upload_history_store.is_processed(("movie", 42))


def test_send_to_tracker_series_without_tmdb_id_skips_duplicate_check_with_a_warning(tmp_path, monkeypatch):
    """tmdb_id absent reste possible mais anormal cote serie aussi : Sonarr
    expose bien un `tmdbId` (confirme en conditions reelles, 2026-09-06 --
    voir gapscan.py:scan_series_season), donc ce n'est PAS une limitation
    permanente. Seul un cas rare (Sonarr n'a pas trouve de correspondance
    TMDB pour cette serie precise) laisserait tmdb_id absent ici."""
    staged = tmp_path / "Show.S01.MULTI.VFF.1080p.WEB.AC3.x264-TEAM"
    staged.mkdir()
    torrent = tmp_path / "Show.S01.MULTI.VFF.1080p.WEB.AC3.x264-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Show.S01.MULTI.VFF.1080p.WEB.AC3.x264-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeSonarrClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_series_details(self, series_id):
            from nfogen.sonarr_client import SonarrSeriesDetails
            return SonarrSeriesDetails(overview="Synopsis serie.")

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.SonarrClient", FakeSonarrClient)
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_sonarr",
        lambda: ("http://sonarr.local", "sonarr-key"),
    )

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def create_draft(self, **kwargs):
            return {"id": 556, "url": "https://c411.org/user/drafts/556"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    result = send_to_tracker(
        release_name="Show.S01.MULTI.VFF.1080p.WEB.AC3.x264-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="series", sonarr_series_id=99, season_number=1,
        # tmdb_id absent : cas desormais rare cote serie (voir docstring)
    )

    assert result.draft_id == 556
    assert result.duplicate_warning is not None
    assert "TMDB" in result.duplicate_warning


def test_send_to_tracker_movie_without_tmdb_id_warns(tmp_path, monkeypatch):
    """Contrairement a une serie (voir le test precedent), un film sans
    tmdb_id est anormal -- Radarr est TMDB-natif -- donc toujours signale."""
    staged = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.MULTI.VFF.1080p.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def create_draft(self, **kwargs):
            return {"id": 557, "url": "https://c411.org/user/drafts/557"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    result = send_to_tracker(
        release_name="Movie.2020.MULTI.VFF.1080p.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", radarr_movie_id=42,
        # tmdb_id absent : anormal cote film, doit rester signale
    )

    assert result.draft_id == 557
    assert result.duplicate_warning is not None
    assert "TMDB" in result.duplicate_warning


def test_send_to_tracker_updates_an_existing_draft_when_draft_id_given(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeRadarrClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_movie_details(self, movie_id):
            from nfogen.radarr_client import RadarrMovieDetails
            return RadarrMovieDetails()

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.RadarrClient", FakeRadarrClient)
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_radarr",
        lambda: ("http://radarr.local", "radarr-key"),
    )

    captured: dict = {}

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            return []

        def update_draft(self, draft_id, **kwargs):
            captured["draft_id"] = draft_id
            return {"id": draft_id, "url": f"https://c411.org/user/drafts/{draft_id}"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    result = send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", radarr_movie_id=1, tmdb_id=1, draft_id=555,
    )

    assert captured["draft_id"] == 555
    assert result.draft_id == 555


def _basic_send_to_tracker_mocks(monkeypatch) -> None:
    """Setup minimal partage par les tests TMDB ci-dessous : tracker
    configure, brouillon accepte, aucun Radarr/Sonarr (non pertinent pour
    ces tests -- seul l'appel TMDB nous interesse)."""
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            return []

        def create_draft(self, **kwargs):
            return {"id": 900, "url": "https://c411.org/user/drafts/900"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)


def test_send_to_tracker_calls_tmdb_when_key_configured_and_tmdb_id_present(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    _basic_send_to_tracker_mocks(monkeypatch)
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tmdb_api_key", lambda: "tmdb-secret"
    )
    calls: list[str] = []

    class FakeTMDBClient:
        def __init__(self, api_key, **kwargs):
            calls.append(api_key)

        def get_movie_extra(self, tmdb_id):
            return TMDBExtraDetails(country="France", vote_average=7.8, creators=[])

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.TMDBClient", FakeTMDBClient)

    send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", tmdb_id=603,
    )

    assert calls == ["tmdb-secret"]


def test_send_to_tracker_skips_tmdb_when_key_not_configured(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    _basic_send_to_tracker_mocks(monkeypatch)
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tmdb_api_key", lambda: None
    )
    instantiated: list[bool] = []
    monkeypatch.setattr(
        "nfogen.upload_prep.TMDBClient",
        lambda *a, **k: instantiated.append(True),
    )

    send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", tmdb_id=603,
    )

    assert instantiated == []


def test_send_to_tracker_tmdb_failure_does_not_block_send(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    _basic_send_to_tracker_mocks(monkeypatch)
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tmdb_api_key", lambda: "tmdb-secret"
    )

    class FailingTMDBClient:
        def __init__(self, api_key, **kwargs):
            pass

        def get_movie_extra(self, tmdb_id):
            raise TMDBError("boom")

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.TMDBClient", FailingTMDBClient)

    result = send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", tmdb_id=603,
    )

    assert result.draft_id == 900  # n'a pas leve, la description s'est generee sans TMDB


def test_send_to_tracker_direct_adds_torrent_to_qbittorrent_on_success(tmp_path, monkeypatch):
    """Retour utilisateur, 2026-09-07 : le torrent uploade directement
    (source=C411 deja inscrit, voir torrent_builder.py) n'etait jamais
    ajoute a qBittorrent -- deux etapes deliberement separees jusqu'ici
    (voir seed-queue), mais desormais automatique pour l'upload direct
    seulement (jamais pour un brouillon, qui reste prive tant que
    l'utilisateur ne le finalise pas lui-meme)."""
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent-bytes")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_qbittorrent",
        lambda: ("http://qbittorrent.local:8080", "admin", "secret", True),
    )

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            return []

        def upload_torrent(self, **kwargs):
            return {"id": 777, "url": "/torrents/abc123"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    added: dict = {}

    class FakeQBittorrentClient:
        def __init__(self, *args, **kwargs):
            pass

        def add_torrent(self, torrent_bytes, save_path, filename, **kwargs):
            added["torrent_bytes"] = torrent_bytes
            added["save_path"] = save_path
            added["filename"] = filename

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.QBittorrentClient", FakeQBittorrentClient)

    result = send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", tmdb_id=603, direct=True,
    )

    assert added["torrent_bytes"] == b"torrent-bytes"
    assert added["save_path"] == str(tmp_path)
    assert added["filename"] == "Movie.2020.BluRay-TEAM.torrent"
    assert result.seed_warning is None


def test_send_to_tracker_draft_never_adds_to_qbittorrent(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent-bytes")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_qbittorrent",
        lambda: ("http://qbittorrent.local:8080", "admin", "secret", True),
    )

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            return []

        def create_draft(self, **kwargs):
            return {"id": 555, "url": "https://c411.org/user/drafts/555"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    called = []
    monkeypatch.setattr(
        "nfogen.upload_prep.QBittorrentClient", lambda *a, **k: called.append(True)
    )

    send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", tmdb_id=603, direct=False,
    )

    assert called == []


def test_send_to_tracker_direct_seed_failure_does_not_block_upload_but_warns(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent-bytes")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_qbittorrent",
        lambda: ("http://qbittorrent.local:8080", "admin", "secret", True),
    )

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            return []

        def upload_torrent(self, **kwargs):
            return {"id": 777, "url": "/torrents/abc123"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    class FailingQBittorrentClient:
        def __init__(self, *args, **kwargs):
            pass

        def add_torrent(self, torrent_bytes, save_path, filename, **kwargs):
            raise QBittorrentError("Connexion échouée")

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.QBittorrentClient", FailingQBittorrentClient)

    result = send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", tmdb_id=603, direct=True,
    )

    assert result.draft_id == 777  # l'upload a quand meme reussi
    assert result.seed_warning is not None
    assert "qBittorrent" in result.seed_warning


def test_send_to_tracker_direct_seed_warns_when_qbittorrent_not_configured(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent-bytes")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_qbittorrent", lambda: None
    )

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            return []

        def upload_torrent(self, **kwargs):
            return {"id": 777, "url": "/torrents/abc123"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    result = send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", tmdb_id=603, direct=True,
    )

    assert result.seed_warning is not None


def test_send_to_tracker_direct_calls_upload_torrent_not_drafts(tmp_path, monkeypatch):
    """Retour d'un membre de l'equipe C411, 2026-09-07 : vrai endpoint
    d'upload direct (POST /api/torrents), distinct des brouillons."""
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )
    calls: list[str] = []

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            return []

        def upload_torrent(self, **kwargs):
            calls.append("upload_torrent")
            return {"id": 777, "url": "/torrents/abc123"}

        def create_draft(self, **kwargs):
            calls.append("create_draft")
            return {"id": 555, "url": "https://c411.org/user/drafts/555"}

        def update_draft(self, draft_id, **kwargs):
            calls.append("update_draft")
            return {"id": draft_id, "url": "https://c411.org/user/drafts/555"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    result = send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", tmdb_id=603, direct=True,
        draft_id=999,  # ignore en mode direct -- ne doit jamais declencher update_draft
    )

    assert calls == ["upload_torrent"]
    assert result.draft_id == 777


def test_send_to_tracker_direct_prefixes_relative_url_with_tracker_domain(tmp_path, monkeypatch):
    staged = tmp_path / "Movie.2020.BluRay-TEAM.mkv"
    staged.write_bytes(b"video")
    torrent = tmp_path / "Movie.2020.BluRay-TEAM.torrent"
    torrent.write_bytes(b"torrent")
    nfo = tmp_path / "Movie.2020.BluRay-TEAM.nfo"
    nfo.write_text("General\nFormat : Matroska", encoding="utf-8")

    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker",
        lambda profile: ("api-key", "https://c411.org"),
    )

    class FakeUploadClient:
        def __init__(self, *args, **kwargs):
            pass

        def check_duplicates(self, tmdb_id, tmdb_type):
            return []

        def upload_torrent(self, **kwargs):
            return {"id": 777, "url": "/torrents/abc123"}

        def close(self):
            pass

    monkeypatch.setattr("nfogen.upload_prep.C411UploadClient", FakeUploadClient)

    result = send_to_tracker(
        release_name="Movie.2020.BluRay-TEAM",
        staged_path=str(staged), torrent_path=str(torrent), nfo_path=str(nfo),
        profile="c411", media_type="movie", tmdb_id=603, direct=True,
    )

    assert result.draft_url == "https://c411.org/torrents/abc123"


def test_send_to_tracker_requires_tracker_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_tracker", lambda profile: None
    )
    with pytest.raises(ValueError, match="[Cc]l[eé]"):
        send_to_tracker(
            release_name="X", staged_path="/x.mkv", torrent_path="/x.torrent", nfo_path="/x.nfo",
            profile="c411", media_type="movie",
        )


# --------------------------------------------------------------------------- #
# Audit securite, 2026-09-09 : source_path/staged_path/staged_name doivent
# etre valides -- avant ce correctif, un appelant authentifie pouvait forger
# n'importe quel chemin pour faire lire/copier/decoder un fichier arbitraire
# du serveur (voir AUTOMATION.md). Les tests ci-dessus restent inchanges
# (neutralises par la fixture autouse _allow_all_paths_by_default) ; ceux-ci
# reactivent les VRAIES fonctions pour prouver l'application reelle du
# controle.
# --------------------------------------------------------------------------- #
class _FakeGapResult:
    def __init__(self, local_paths):
        self.local_paths = local_paths


def test_path_within_accepts_a_path_under_root(tmp_path):
    from nfogen.upload_prep import _path_within

    root = tmp_path / "staging"
    root.mkdir()
    child = root / "sub" / "file.mkv"
    assert _path_within(str(child), str(root)) is True


def test_path_within_rejects_dot_dot_traversal(tmp_path):
    from nfogen.upload_prep import _path_within

    root = tmp_path / "staging"
    root.mkdir()
    escaped = root / ".." / "outside.mkv"
    assert _path_within(str(escaped), str(root)) is False


def test_path_within_rejects_absolute_override(tmp_path):
    """Cas reel de l'audit : pathlib.Path(root) / '/etc/x' renvoie
    directement Path('/etc/x') -- _path_within doit quand meme le
    detecter via .resolve(), pas via l'operateur '/' seul."""
    from nfogen.upload_prep import _path_within

    root = tmp_path / "staging"
    root.mkdir()
    outside = tmp_path / "elsewhere" / "evil.mkv"
    assert _path_within(str(outside), str(root)) is False


def test_validate_staged_path_raises_when_staging_dir_not_configured(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: None)
    with pytest.raises(ValueError, match="dossier de mise en scène"):
        _real_validate_staged_path("/anything.mkv")


def test_validate_staged_path_accepts_a_path_under_staging_dir(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    _real_validate_staged_path(str(staging_dir / "Movie.2020.mkv"))  # ne leve pas


def test_validate_staged_path_rejects_a_path_outside_staging_dir(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )
    with pytest.raises(ValueError, match="dossier de mise en scène"):
        _real_validate_staged_path(str(tmp_path / "outside.mkv"))


def test_validate_known_source_paths_accepts_a_path_seen_in_a_scan(monkeypatch):
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_runner.results", lambda **k: [_FakeGapResult(["/nas/movie.mkv"])]
    )
    _real_validate_known_source_paths(["/nas/movie.mkv"])  # ne leve pas


def test_validate_known_source_paths_rejects_a_path_never_seen_in_a_scan(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep.gapscan_runner.results", lambda **k: [])
    with pytest.raises(ValueError, match="non reconnu"):
        _real_validate_known_source_paths(["/etc/shadow"])


def test_commit_upload_rejects_a_source_path_never_seen_in_a_scan(tmp_path, monkeypatch):
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    _configure_staging(monkeypatch, staging_dir)
    monkeypatch.setattr("nfogen.upload_prep._validate_known_source_paths", _real_validate_known_source_paths)
    monkeypatch.setattr("nfogen.upload_prep.gapscan_runner.results", lambda **k: [])
    files = [ProposedFile(source_path=str(tmp_path / "forged.mkv"), staged_name="X.mkv")]

    with pytest.raises(ValueError, match="non reconnu"):
        commit_upload("X", files)


def test_commit_upload_rejects_a_staged_name_escaping_staging_dir(tmp_path, monkeypatch):
    """Cas de l'audit : staged_name='/etc/cron.d/evil' (ou '../../evil')
    ne doit jamais aboutir a une ecriture hors de staging_dir."""
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    _configure_staging(monkeypatch, staging_dir)
    monkeypatch.setattr("nfogen.upload_prep.validate_staged_path", _real_validate_staged_path)
    source = _make_source(tmp_path, "source.mkv")
    files = [ProposedFile(source_path=source, staged_name=str(tmp_path / "outside" / "evil.mkv"))]

    with pytest.raises(ValueError, match="dossier de mise en scène"):
        commit_upload("X", files)
    assert not (tmp_path / "outside" / "evil.mkv").exists()


def test_preview_upload_rejects_local_paths_never_seen_in_a_scan(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep._validate_known_source_paths", _real_validate_known_source_paths)
    monkeypatch.setattr("nfogen.upload_prep.gapscan_runner.results", lambda **k: [])

    with pytest.raises(ValueError, match="non reconnu"):
        preview_upload(["/nas/forged.mkv"])


def test_preview_upload_season_pack_rejects_local_paths_never_seen_in_a_scan(monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep._validate_known_source_paths", _real_validate_known_source_paths)
    monkeypatch.setattr("nfogen.upload_prep.gapscan_runner.results", lambda **k: [])
    season_pack = SeasonPackRequest(
        title="Lucifer", team="Frosties", is_full_series=True,
        seasons=[SeasonPackSeasonFiles(season_number=5, local_paths=["/nas/forged.mkv"])],
    )

    with pytest.raises(ValueError, match="non reconnu"):
        preview_upload([], season_pack=season_pack)


def test_send_to_tracker_rejects_a_staged_path_outside_staging_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("nfogen.upload_prep.validate_staged_path", _real_validate_staged_path)
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    monkeypatch.setattr(
        "nfogen.upload_prep.gapscan_config_store.effective_staging_dir", lambda: str(staging_dir)
    )

    with pytest.raises(ValueError, match="dossier de mise en scène"):
        send_to_tracker(
            release_name="X",
            staged_path=str(tmp_path / "etc" / "shadow"),
            torrent_path=str(staging_dir / "X.torrent"),
            nfo_path=str(staging_dir / "X.nfo"),
            profile="c411", media_type="movie",
        )
