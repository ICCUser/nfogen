# Seed d'une release C411 existante déjà possédée — design

## Contexte

Retour utilisateur (2026-09-09) : "Pareil sur les media que je possede
dans ma bibliotheque (deja couvert) s'il sont deja couvert et
exactement pareil que c411 [...] est-ce pas possible de recuperer le
torrent [...] afin de seed ce meme fichier ? Si compliqué a faire,
peutere marquer, un message, seed possible."

Un titre `GapStatus.COVERED` signifie qu'une release au moins aussi
bonne existe déjà sur C411 — aujourd'hui, ça n'ouvre aucune action :
l'utilisateur ne peut ni uploader (déjà couvert, refusé par le
validateur anti-doublon) ni seeder facilement le fichier qu'il possède
déjà, alors qu'il pourrait s'agir du **même encode exact**.

## Faisabilité technique confirmée (2026-09-09)

- **Règles C411** : télécharger/seeder le torrent d'un autre membre est
  le principe même de l'usage attendu d'un tracker privé (confirmé par
  l'utilisateur).
- **Téléchargement programmatique** : confirmé en conditions réelles
  contre `https://c411.org/api` —
  `GET /api?t=get&id={guid}&apikey={cle}` renvoie directement le
  `.torrent` (`Content-Type: application/x-bittorrent`,
  `Content-Disposition: attachment; filename="..."`). **Distinct** du
  cas déjà documenté dans `nfogen/qbittorrent_client.py` (télécharger
  le torrent **re-signé de son propre upload** après modération, qui
  lui exige une session navigateur, pas la clé API — deux endpoints
  différents, la confusion serait facile). `guid` est déjà capturé par
  `TorznabRelease.guid` (`nfogen/torznab_client.py`), lui-même déjà
  conservé dans `GapResult.c411_matches` (persistant sur disque, voir
  `gapscan_results_store.py`).

## Objectif

Pour un titre `COVERED` dont le fichier local correspond, avec une
forte confiance, à une release C411 existante précise : télécharger
son `.torrent`, l'ajouter à qBittorrent en pause pointé sur le fichier
local déjà en place, laisser qBittorrent vérifier réellement les
pièces, puis reprendre le seed automatiquement si — et seulement si —
la vérification confirme une correspondance parfaite.

## Hors périmètre (explicitement)

- Le `.nfo` de la release existante n'est **pas** récupéré (l'API
  Torznab ne l'expose pas séparément ; hors sujet — le `.nfo` local de
  l'utilisateur, s'il existe, reste inchangé).
- Aucune modification de `_classify()`/`GapStatus` — `seed_match` est
  une information **additionnelle** sur un item déjà `COVERED`, pas un
  nouveau statut.
- Pas de correspondance "quasi identique" tolérante (langue en plus,
  résolution différente, etc.) — uniquement une correspondance
  candidate **stricte** au pré-filtre, elle-même reconfirmée par le
  hash-check qBittorrent avant tout seed réel.

## A. Détection du candidat (pré-filtre, avant tout téléchargement)

**Ce qui est réellement comparable** (limite volontairement posée ici,
pour ne pas promettre plus que ce que le projet parse déjà) : un
`TorznabRelease` de C411 n'a qu'un **titre texte** — pas de MediaInfo.
La comparaison se fait donc sur ce que `quality.parse_release_name()`
extrait déjà d'un nom de release (résolution/source/codec
vidéo/langues — **pas** le codec audio ni les canaux, non parsés depuis
un simple nom de fichier dans ce projet) plus le tag d'équipe
(`name_proposal.extract_team_tag()`, déjà utilisé pour `LibraryItem.team`)
et la taille exacte du fichier local (`os.path.getsize`, jamais
capturée aujourd'hui — calculée à la volée, pas besoin de toucher
`RadarrMovieFile`/`SonarrSeasonFile`).

```python
# nfogen/seed_match.py (nouveau module)

@dataclass
class SeedMatchCandidate:
    guid: str
    release_name: str


def find_seed_match(
    local_quality: ReleaseQuality,
    local_team: Optional[str],
    local_size: int,
    matches: list[TorznabRelease],
) -> Optional[SeedMatchCandidate]:
    """Une SEULE release de `matches` doit correspondre EXACTEMENT :
    meme resolution/source/codec/langues (ReleaseQuality == a l'exclusion
    de `raw`), meme tag d'equipe (extract_team_tag sur le titre C411), et
    `TorznabRelease.size == local_size` (octet pres -- champ deja
    parse depuis l'attribut torznab `size`). Zero ou plusieurs
    correspondances (ambigu) -> None, jamais un choix devine."""
```

Exposé par `GET /gapscan/library` : `LibraryItem` gagne
`seed_match: Optional[dict]` (`{"guid": str, "release_name": str}`),
calculé uniquement pour un item `status == "covered"` avec
`path_resolved` vrai. Comme pour `season_packs`, calculé côté
`gapscan_library.list_library()` à partir de `previous_results`
(aucun nouvel appel réseau).

## B. Téléchargement + vérification (tâche de fond)

Même patron que `integrity_job_runner.py` (sous-projet 7, déjà livré) :
job en mémoire, `job_id`, polling, jamais de blocage de page.

```python
# nfogen/torznab_client.py -- nouvelle methode sur TorznabClient
def download(self, guid: str) -> bytes:
    """`GET /api?t=get&id={guid}&apikey=...` -- renvoie les octets bruts
    du .torrent. Meme throttle/retry-apres-429 que _search() (reutilise
    _throttle(), meme gestion d'erreur -> TorznabError)."""
```

```python
# nfogen/seed_match_job_runner.py (nouveau module)
class SeedMatchJobState(str, Enum):
    DOWNLOADING = "downloading"
    CHECKING = "checking"
    DONE = "done"        # verifie ET identique -> deja repris en seed
    MISMATCH = "mismatch"  # verifie mais PAS identique -> reste en pause
    ERROR = "error"
    CANCELLED = "cancelled"
```

Déroulé de `_run(job_id, guid, local_dir, release_name)` :
1. `tracker_client.download(guid)` → `torrent_bytes`.
2. Écrit `torrent_bytes` dans un fichier temporaire (`tempfile`), lit
   son infohash via `torf.Torrent.read(tmp_path)` (bibliothèque déjà
   utilisée par `torrent_builder.py` — lire un `.torrent` existant,
   jamais utilisé jusqu'ici, mais même import déjà en place).
3. `qbittorrent_client.add_torrent(torrent_bytes, save_path=local_dir, filename=f"{release_name}.torrent", paused=True, tags="NFOGEN")`
   (voir C. ci-dessous pour `paused`/`tags`, nouveaux paramètres).
4. État `CHECKING` — poll `qbittorrent_client.list_torrents()`
   (déjà existant) toutes les 1.5s, cherche l'entrée dont `hash`
   correspond à l'infohash de l'étape 2.
   - `progress == 1.0` **et** `state` ∈ `{"pausedUP", "queuedUP", "checkedUP"}`
     (qBittorrent : vérification terminée, fichier complet) → mise à
     jour `state=DONE` et reprise du seed (`qbittorrent_client.resume(hash)`,
     nouvelle méthode, `POST /api/v2/torrents/resume`).
   - `state` ∈ `{"missingFiles", "error"}`, ou vérification terminée
     avec `progress < 1.0` → `state=MISMATCH`, **jamais repris** — le
     torrent reste en pause dans qBittorrent (visible, supprimable
     manuellement par l'utilisateur), `result.warning` explique
     pourquoi.
   - **⚠ Chaînes d'état qBittorrent non vérifiées contre une instance
     réelle** (même prudence que le N+1 Sonarr du 2026-09-09, où une
     hypothèse non testée a cassé la Bibliothèque en production) — la
     Task correspondante du plan d'implémentation devra prévoir un test
     réel (ou une confirmation de l'utilisateur via son interface
     qBittorrent) avant de considérer ce point acquis.
5. Timeout de vérification (`_CHECK_TIMEOUT_SECONDS = 300.0`, un gros
   fichier peut prendre plusieurs minutes à re-hasher) → `ERROR`,
   message explicite ("vérification qBittorrent trop longue — vérifie
   manuellement dans son interface").

`cancel_event` (même mécanisme que les autres jobs) : si positionné
avant l'étape 3, n'ajoute jamais le torrent à qBittorrent ; positionné
après, le job cesse de poller mais **ne retire pas** le torrent déjà
ajouté à qBittorrent (cohérent avec le principe déjà établi ailleurs
dans le projet : jamais de suppression automatique côté qBittorrent).

## C. `qbittorrent_client.py` — extensions minimes

```python
def add_torrent(
    self, torrent_bytes: bytes, save_path: str, filename: str = "release.torrent",
    *, paused: bool = False, tags: Optional[str] = None,
) -> None:
    """`paused` (nouveau) : ajoute sans demarrer -- utilise ici pour
    laisser la verification qBittorrent (hash-check) se terminer avant
    toute decision de seed reelle. `tags` (nouveau, retour utilisateur
    2026-09-09 : "ajoute un tag a qbit, tag NFOGEN") : etiquette tout
    torrent ajoute par nfogen, y compris pour l'auto-seed existant apres
    upload direct (sous-projet 6) -- distingue en un coup d'oeil les
    torrents geres par nfogen des autres dans l'interface qBittorrent."""

def resume(self, torrent_hash: str) -> None:
    """`POST /api/v2/torrents/resume` (hashes=<hash>) -- reprend un
    torrent ajoute en pause. Nouveau, uniquement utilise par
    seed_match_job_runner.py apres verification reussie."""
```

`send_to_tracker(direct=True)` (`nfogen/upload_prep.py`, sous-projet 6)
gagne `tags="NFOGEN"` sur son appel `add_torrent()` existant — même
étiquette partout, cohérence.

## D. API HTTP

```
POST /gapscan/seed-match/start   {"key": str, "guid": str, "release_name": str}
     -> {"job_id": str}
GET  /gapscan/seed-match-jobs/{job_id}
     -> {job_id, state, error, result: {passed, warning} | None}
POST /gapscan/seed-match-jobs/{job_id}/cancel
```

`key`/`guid` revalidés côté serveur contre `gapscan_runner.results()`
(même principe que `_validate_known_source_paths`, audit sécurité
2026-09-09 : ne jamais faire confiance à un `guid`/chemin fourni tel
quel par le client sans le rattacher à un scan connu) — le `guid` doit
figurer dans les `c411_matches` du résultat identifié par `key`, sans
quoi 400.

## E. Frontend

Bouton **"Seed possible"** dans la Bibliothèque, visible uniquement
quand `item.seed_match` est présent (à côté du badge de statut,
`STATUS_BADGE_CLASS.covered`). Clic → démarre le job, barre de
progression inline (même style que "Confirmer"/"Vérification du
fichier" déjà en place), résultat final :
- `DONE` : "✅ Mis en seed ({release_name})".
- `MISMATCH` : "⚠ Le fichier téléchargé ne correspond pas exactement — resté en pause dans qBittorrent, à vérifier/supprimer manuellement."
- `ERROR` : message d'erreur brut.

## Erreurs — résumé

| Situation | Résultat |
|---|---|
| Zéro ou plusieurs candidats au pré-filtre | Pas de `seed_match` exposé, aucun bouton |
| `guid` non retrouvé dans un scan connu (sécurité) | 400 immédiat |
| Téléchargement échoue (réseau, 429 après retry) | Job `ERROR` |
| qBittorrent hash-check < 100% ou fichiers manquants | Job `MISMATCH`, torrent laissé en pause, jamais supprimé |
| Vérification qBittorrent trop longue (> 5 min) | Job `ERROR`, message explicite |
| Annulation avant ajout | Rien n'est ajouté à qBittorrent |
| Annulation après ajout | Le torrent ajouté reste en pause dans qBittorrent (jamais retiré automatiquement) |

## Tests

- `tests/test_seed_match.py` : `find_seed_match()` (candidat unique,
  ambigu, taille différente, team différente, résolution différente,
  aucune release).
- `tests/test_torznab_client.py` : nouveau test `download()` (mock
  httpx, vérifie `t=get`/`id`/`apikey`, throttle réutilisé, gestion
  d'erreur).
- `tests/test_qbittorrent_client.py` : `add_torrent(paused=True, tags=...)`
  envoie bien ces champs au formulaire ; nouveau `resume()`.
- `tests/test_seed_match_job_runner.py` : même style que
  `test_integrity_job_runner.py` (mock des dépendances, DONE/MISMATCH/ERROR/CANCELLED,
  timeout de vérification).
- `tests/test_api.py` : 3 nouveaux endpoints + validation `guid` contre
  un scan connu (400 si absent).
- `tests/test_gapscan_library.py` : `LibraryItem.seed_match` calculé
  correctement (présent seulement si `status == covered` et un
  candidat unique).
- Frontend : `LibraryPage.test.tsx` (bouton visible/absent selon
  `seed_match`), nouveau composant ou bloc inline testé pour le
  polling/les 3 états finaux.
