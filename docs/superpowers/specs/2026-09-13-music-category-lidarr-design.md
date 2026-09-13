# Catégorie Musique (Audio, Lidarr) — Design

## Contexte et problème

nfogen automatise aujourd'hui le pipeline gap→NFO→torrent→upload pour la
catégorie vidéo (films/séries, via Radarr/Sonarr). Le profil C411 déclare
pourtant déjà plusieurs catégories (`GET /profiles` → `"c411": ["audio",
"ebook", "game", "print3d", "video"]`), et le dossier complet des pages
d'aide C411 fourni par l'utilisateur couvre toutes ces catégories, pas
seulement la vidéo : l'intention est d'étendre nfogen à l'ensemble des
catégories que C411 accepte, en commençant par la Musique.

**Bonne surprise en explorant le code** : une partie du travail existe
déjà, orpheline — `nfogen/extract.py::extract_album()` extrait déjà
artiste/album/genre/année/codec/bitrate/tracklist depuis un vrai dossier
audio (MediaInfo), et la CLI (`nfogen -c audio -i /dossier/album -o
album.nfo`) génère déjà un NFO audio conforme au format officiel
(`Description & NFO - C411`, exemple "FervexPrez"). Ce qui manque est tout
l'automatisme autour : découverte de bibliothèque (Lidarr), détection de
gaps face au catalogue C411, proposition de nom de release, description
BBCode dédiée, et upload effectif.

## Périmètre (décomposition validée par l'utilisateur, 2026-09-13)

La catégorie Audio complète de C411 couvre Musique (albums), Podcast/Radio
et Samples — trois formats de nommage et trois logiques de source
différentes. Ce document couvre **uniquement Musique** (albums d'artistes,
via Lidarr). Podcast/Radio et Samples sont des sous-projets séparés, à
traiter après validation de celui-ci en conditions réelles — ils
réutiliseront la même infrastructure (moteur déclaratif, template Jinja
par catégorie) mais avec leurs propres règles de nommage et sans source
Lidarr (upload manuel de fichiers locaux, pas de découverte de
bibliothèque).

## Contexte technique existant (réutilisé, pas redérivé)

- **`nfogen/radarr_client.py` / `nfogen/sonarr_client.py`** : clients REST
  en lecture seule, patron à reproduire pour Lidarr (`RadarrMovieFile`
  /`SonarrSeriesFile` → `LidarrAlbum`).
- **`nfogen/extract.py::extract_album(source: Path) -> dict[str, Any]`** :
  DÉJÀ FAIT. Renvoie `artist`, `album`, `genre`, `year`, `codec`, `format`,
  `overall_bit_rate`, `bit_rate_mode`, `channel`, `quality`,
  `writing_library`, `encoding_settings`, `tracklist` (liste de pistes
  avec `index`/`name`/`title`/`artist`/`size`/`duration`), `total_size`,
  `total_duration`, `playing_time`. Utilisé aujourd'hui uniquement par la
  CLI (`nfogen/cli.py`, `-c audio`).
- **`nfogen/profile_store.py`** : `_TEMPLATE_FILENAMES` mappe déjà chaque
  catégorie (`audio`, `ebook`, `game`, `print3d`, `video`) à son propre
  fichier `.j2` de template NFO — le template `audio.j2` du profil c411
  existe déjà et produit le format "FervexPrez" (voir dump complet dans le
  profil, déjà vérifié cette session). **Seul `upload_description.j2` (la
  description BBCode envoyée à l'API C411) est unique et 100% vidéo**
  aujourd'hui (référence `video_codec`/`resolution`/`subtitle_rows`, etc.)
  — il faudra le rendre sélectionnable par catégorie.
- **`nfogen/gapscan.py`** : `scan_movie()`/`scan_series_season()`
  produisent des `GapResult(media_type="movie"|"series", ...)` comparés au
  catalogue C411. `run_gapscan()` orchestre les deux media_types déjà en
  parallèle de manière symétrique (voir lignes 320-430) — patron à
  reproduire pour `media_type="music"`.
- **`nfogen/name_proposal.py`** : `propose_video_release_name()` /
  `propose_season_pack_name()`, moteur déclaratif par alias
  (`_detect_via_aliases`), mais bâti entièrement autour du gabarit vidéo à
  jetons séparés par points (`{title}.{identifier}.{language}...`). Le
  format Musique (`Artiste.Nom.Année.Codec[Bitrate.Frequence]-TAG`, avec
  un suffixe entre crochets dont le CONTENU dépend du type de codec —
  bit/fréquence pour le lossless, kbps pour le lossy) a une forme trop
  différente pour être forcée dans ce moteur : nouvelle fonction dédiée.
- **`nfogen/c411_upload_options.py`** / **`nfogen/tracker_profile.py`** :
  mapping déclaratif catégorie/sous-catégorie/options déjà générique
  (`build_category_ids(profile, media_type, genre)`,
  `build_options(profile, capture_values, release_name, season_number)`)
  — juste besoin de nouvelles entrées de config pour `media_type="music"`,
  aucun changement de mécanisme.
- **Page officielle `Le Nommage de l'upload - C411`** (déjà lue), section
  Musique : `Format : Artiste.Nom.Année.Codec[Bitrate.Frequence]-TAG`,
  exemples `The.Weeknd.Blinding.Lights.2019.FLAC[16bit.44.1kHz]-NOTAG` et
  `Demi.Lovato.It.s.Not.That.Deep.Little.Bit.Extra.Version.2025.MP3[320kbps]-NOTAG`.
- **Page officielle `Audio - C411`** (déjà lue) : types acceptés (albums,
  coffrets `[COFFRET]`, discographies, intégrales), formats (lossless
  FLAC/ALAC/WAV/WV/AIF, lossy MP3/M4A/OGG/WMA), bitrates minimums (MP3 320
  kbps constant, AAC 256 kbps), règles de doublons (même format+bitrate =
  doublon ; FLAC jamais un doublon sur la qualité), interdictions
  (transcodage upmix MP3→FLAC, rip Spotify/Deezer/Apple Music compte
  gratuit, singles isolés < 20 min).
- **Page officielle `C411_reference.htm`** (déjà lue) : `categoryId=3`
  (Audio), `subcategoryId=18` (Musique) confirmés. Les ids d'OPTIONS
  spécifiques à l'Audio (la doc `C411_API.htm` montre un exemple d'upload
  musique avec `options={"15": 187, "16": 196}` sans jamais documenter ce
  que représentent les types 15/16) ne sont PAS dans la doc lue — à
  vérifier en direct (`GET /api/categories/18/options`) au moment de
  l'implémentation, jamais deviné.

## Décisions de cadrage

1. **Lidarr dès le départ** (décision utilisateur explicite) : même
   niveau d'automatisation que Radarr/Sonarr pour la vidéo — découverte de
   bibliothèque, détection de gaps, proposition de nom, upload.
2. **Un module par responsabilité, symétrique à l'existant** : pas de
   branchement `if media_type == "music"` dispersé dans les fichiers
   vidéo existants — un `lidarr_client.py`, une extension de `gapscan.py`
   pour le scan musical (ou un `gapscan_music.py` séparé si le mélange
   dans `gapscan.py` alourdit trop ce fichier — à trancher à l'écriture du
   plan selon la taille réelle du diff), un `propose_music_release_name()`
   dans `name_proposal.py`.
3. **Détection de doublons musique** : contrairement au film/série
   (matching fiable par `tmdbId` via `GET /api/torrents/by-tmdb`), aucun
   identifiant universel équivalent n'est documenté pour la musique.
   **Point à vérifier en direct avant d'écrire le plan d'implémentation** :
   existe-t-il un endpoint `by-musicbrainzid` (Lidarr expose des
   MusicBrainz IDs pour artiste/album) ? À défaut, repli sur une recherche
   texte (`t=search&q=Artiste Album`) via le flux Torznab déjà utilisé
   pour la catégorie vidéo — moins fiable (faux positifs/négatifs
   possibles sur homonymes), mais fonctionnel pour un premier jet, à
   documenter comme limite connue plutôt que bloquant.
4. **Template de description BBCode par catégorie** :
   `render_upload_description()` devient paramétrée par catégorie
   (`render_upload_description(profile, category, context)`), avec un
   nouveau template `upload_description_audio.j2` (ou équivalent — nom
   exact à trancher à l'implémentation) construit sur le modèle de
   l'exemple officiel FervexPrez (Artiste/Album/Genre/Année/Codec/Format/
   Bitrate/Canal/Tracklist), jamais un réemploi du template vidéo existant.
5. **Bibliothèque (UI)** : réutilisation de `library_inventory_store.py`
   (déjà générique par `LibraryItem`), un `media_type="music"` de plus
   dans le même cache — pas de nouveau mécanisme de synchro/cache
   dupliqué. Détail d'affichage (onglet séparé vs liste unifiée filtrable)
   à trancher à l'écriture du plan, hors décision architecturale.
6. **Règles de contenu (bitrates minimums, formats interdits, canaux
   autorisés)** : implémentées comme des `cross_checks`/`upscale_checks`
   déclaratifs dans `rules.json -> audio`, même mécanisme que la vidéo
   (`registry.get_validator`), pas de nouvelle logique de validation en
   dur.

## Architecture et flux de données

```
Lidarr (bibliotheque d'artistes/albums suivis)
   |
   v
lidarr_client.py (lecture seule, LidarrAlbum : artiste/album/annee/
                   MusicBrainz IDs/fichiers locaux/taille)
   |
   v
gapscan.py (ou gapscan_music.py) : scan_album() --> GapResult(media_type="music", ...)
   |  (comparaison catalogue C411 : by-musicbrainzid si dispo, sinon recherche texte)
   v
Bibliotheque (UI, /library) --> "Preparer l'upload" (album selectionne)
   |
   v
extract_album() (DEJA FAIT) --> metadata (artiste/album/annee/codec/bitrate/tracklist)
   |
   +--> name_proposal.propose_music_release_name() --> release_name
   |
   +--> profile_store (template audio.j2, DEJA FAIT) --> .nfo
   |
   +--> render_upload_description(profile, "music", context) --> description BBCode
   |        (nouveau template, artiste/album/genre/tracklist/pochette)
   |
   +--> file_staging / torrent_builder (deja generiques, aucun changement)
   |
   +--> c411_upload_options.build_options(...) + C411UploadClient
            (categoryId=3, subcategoryId=18, options Audio a verifier en direct)
```

## Composants

1. **`nfogen/lidarr_client.py`** (nouveau) — client REST Lidarr v1,
   lecture seule, même patron que `radarr_client.py`. `LidarrAlbum` :
   `album_id`, `artist_name`, `album_title`, `release_year`,
   `musicbrainz_album_id`/`musicbrainz_artist_id` (si exposés par
   l'API Lidarr — à vérifier), fichiers locaux (chemins + taille),
   `added_at`. Aucune écriture, aucune modification de la bibliothèque
   Lidarr — même garde-fou que Radarr/Sonarr.

2. **`gapscan.py`** (étendu) ou **`gapscan_music.py`** (nouveau, à
   trancher selon la taille réelle) : `scan_album(album, ...) ->
   GapResult` (même forme que `scan_movie`/`scan_series_season`,
   `media_type="music"`). `run_gapscan()` orchestre un troisième
   media_type en parallèle des deux existants.

3. **`name_proposal.py`** : `propose_music_release_name(artist, title,
   year, codec, bit_rate_kbps, bit_depth, sample_rate_hz, team,
   is_coffret, config) -> NameProposal` — nouvelle fonction, gabarit
   déclaratif (`rules.json -> audio.name_proposal.template`), séparée du
   moteur vidéo. Gère le suffixe conditionnel `[Bitrate.Frequence]`
   (lossless) vs `[Bitrate]` (lossy) et le tag `[COFFRET]` optionnel.

4. **`nfogen/profiles/c411/rules.json`** (étendu) : nouvelle section
   `audio` avec `name_proposal` (gabarit, alias de codec lossless/lossy),
   `cross_checks`/`upscale_checks` pour les bitrates minimums (MP3 320
   kbps, AAC 256 kbps), `tracker.upload.subcategory_id["music"] = 18`, et
   les options Audio (ids à confirmer en direct avant de les écrire).

5. **`render.py`/`upload_prep.py`** : `render_upload_description()` prend
   un paramètre `category` (défaut `"video"` pour compatibilité
   ascendante avec l'existant), charge le template correspondant. Nouveau
   template `upload_description_audio.j2` (ou nom équivalent) dans
   `nfogen/profiles/c411/templates/`.

6. **UI (`frontend/`)** : la page Bibliothèque affiche les items
   `media_type="music"` (filtre/onglet, détail à l'implémentation) ; le
   panneau "Préparer l'upload" gère le cas musique (pas de sélection de
   saison, gestion de tracklist au lieu de pistes vidéo/audio/sous-titres).

## Gestion d'erreur

Mêmes garde-fous que le pipeline vidéo existant, appliqués à l'identique :
- Lidarr injoignable : `gapscan_music`/le scan échoue proprement (erreur
  loggée, jamais de crash), même comportement que Radarr/Sonarr
  aujourd'hui.
- `extract_album()` sur un dossier illisible/vide : lève déjà `ValueError`
  explicite (comportement existant, réutilisé tel quel).
- Détection de doublons par recherche texte (repli, voir décision 3) :
  jamais bloquante — un résultat ambigu ou vide devient un avertissement
  affiché à l'utilisateur ("aucune correspondance fiable trouvée,
  vérifiez manuellement"), jamais un blocage silencieux de l'upload.

## Tests

Même discipline TDD que le reste du projet, un fichier de test par
nouveau module :
1. **`tests/test_lidarr_client.py`** : parsing des réponses Lidarr (mock
   HTTP), gestion d'erreur réseau.
2. **`tests/test_gapscan_music.py`** (ou extension de
   `tests/test_gapscan.py`) : `scan_album()` produit bien un `GapResult`
   cohérent ; `run_gapscan()` inclut le troisième media_type sans casser
   les deux existants (non-régression explicite).
3. **`tests/test_name_proposal.py`** (étendu) : `propose_music_release_name()`
   — cas lossless (FLAC, suffixe bit/fréquence), cas lossy (MP3/AAC,
   suffixe kbps), coffret (`[COFFRET]`), NOTAG.
4. **`tests/test_upload_description.py`** (étendu) : nouveau template
   audio rend bien artiste/album/genre/tracklist ; le template vidéo
   existant reste inchangé (non-régression sur le paramètre `category`
   ajouté).
5. **`tests/test_c411_upload_options.py`** (étendu) : `categoryId=3`/
   `subcategoryId=18` pour `media_type="music"`, options Audio une fois
   les ids réels confirmés.

## Points à vérifier en direct avant/pendant l'implémentation (jamais devinés)

- Ids d'options Audio C411 (`GET /api/categories/18/options`, clé API
  déjà disponible côté serveur).
- Existence d'un endpoint de détection de doublons par MusicBrainz ID
  (sinon repli sur recherche texte, voir décision 3).
- Forme exacte de l'API Lidarr v1 (champs réellement exposés pour
  artist/album/track — à confirmer contre une instance Lidarr réelle si
  l'utilisateur en installe une, ou contre la doc publique Lidarr).
