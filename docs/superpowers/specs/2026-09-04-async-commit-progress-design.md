# Suivi d'avancement asynchrone de "Confirmer" (sous-projet 4c)

**Statut** : approuvé par l'utilisateur (2026-09-04), prêt pour le plan d'implémentation.

## Problème

`POST /gapscan/prepare-upload/commit` (`nfogen/upload_prep.py:commit_upload`)
est aujourd'hui **synchrone** : le navigateur envoie la requête et attend la
réponse HTTP finale avant de rien afficher. Deux étapes internes peuvent
prendre plusieurs minutes sur un gros fichier :

1. **Mise en scène** (`file_staging.py`) : hardlink instantané si NAS/staging
   sont sur le même volume, sinon **repli copie complète** (`shutil.copy2`,
   un seul appel bloquant, aucun retour d'avancement) — incident réel signalé
   par l'utilisateur (2026-09-04) : "je croist qu'il copie le film... je
   reste sur la page à rien faire".
2. **Génération du `.torrent`** (`torrent_builder.py`) : `torf` **hache tout
   le contenu** du fichier mis en scène — également long sur un gros film,
   également invisible aujourd'hui.

Pendant ces deux étapes, l'onglet reste bloqué sur un spinner générique
("Confirmation…") sans autre choix que d'attendre sur place.

## Objectifs (validés avec l'utilisateur)

- Un état d'avancement **couvrant les trois étapes** de Confirmer (copie →
  génération `.nfo` → génération `.torrent`), pas seulement le transfert de
  fichier.
- **Pourcentage précis** (pas juste une étape grossière) pour la copie et le
  hash du torrent.
- Le serveur exécute Confirmer **en tâche de fond** — la page n'a plus
  besoin de rester ouverte/active pendant l'opération.
- **Plusieurs tâches en parallèle** (un `job_id` par clic sur Confirmer, pas
  un verrou global comme GapScan).
- Les tâches en cours (ou récemment terminées) sont **retrouvées après un
  rechargement de page** — pas seulement suivies pendant la session React
  en cours.
- **Annulation** possible d'une tâche en cours.

## Non-objectifs (hors scope, YAGNI)

- Reprise d'une tâche interrompue par un **redémarrage du serveur**
  (`scripts/update.sh` par ex.) — comme pour un scan GapScan en cours, une
  tâche interrompue par un redémarrage est simplement perdue (elle
  disparaît du registre en mémoire) ; l'utilisateur reclique sur Confirmer.
  Documenté, pas résolu ici.
- File d'attente / limite de tâches simultanées — aucune limite n'est
  imposée au nombre de tâches parallèles pour cette livraison (au-delà d'un
  usage raisonnable, l'utilisateur gère lui-même son rythme de clics).
- Historique persistant des tâches terminées au-delà de la session serveur
  (pas de fichier de log dédié) — un registre en mémoire uniquement, comme
  `gapscan_runner.py`.
- Barre de progression pour la génération du `.nfo` (lecture texte quasi
  instantanée, pas de retour utilisateur signalé sur cette étape) — elle
  reste une transition d'état sans pourcentage propre.

## Architecture

### Nouveau module minimal : `nfogen/cancellation.py`

`file_staging.py` et `torrent_builder.py` n'ont aujourd'hui aucune
relation d'import entre eux (deux modules utilitaires indépendants) ; les
deux ont désormais besoin de signaler "annulé en cours de route" de la
même façon. Plutôt que l'un dépende de l'autre pour une simple exception,
ou dupliquer la classe, un module minuscule et neutre :

```python
class OperationCancelled(RuntimeError):
    """Une operation (copie, hachage de torrent...) a ete interrompue via
    un threading.Event fourni par l'appelant (voir commit_job_runner.py)."""
```

Importé par `file_staging.py`, `torrent_builder.py`, et attrapé par
`upload_prep.commit_upload`/`commit_job_runner.py`.

### Nouveau module : `nfogen/commit_job_runner.py`

Registre de tâches en mémoire, calqué sur `gapscan_runner.py` mais **indexé
par `job_id`** (au lieu d'un état global unique) pour permettre plusieurs
tâches concurrentes :

```python
class JobState(str, Enum):
    STAGING = "staging"
    GENERATING_NFO = "generating_nfo"
    BUILDING_TORRENT = "building_torrent"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"

@dataclass
class JobProgress:
    job_id: str
    release_name: str
    state: JobState
    percent: float = 0.0          # 0-100, relatif a l'ETAPE EN COURS
    started_at: float = ...
    finished_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[dict] = None  # CommitResult serialise, une fois DONE
```

- `start(release_name, files, profile) -> str` : crée l'entrée, démarre un
  `threading.Thread(daemon=True)`, renvoie le `job_id` **immédiatement**
  (ne bloque jamais l'appelant).
- `status(job_id) -> Optional[dict]` : état d'une tâche, `None` si
  `job_id` inconnu.
- `list_jobs() -> list[dict]` : toutes les tâches connues (actives et
  terminées) — c'est ce qu'interroge le nouvel encart "Transferts en cours"
  au chargement de la page pour retrouver les tâches en cours après un
  rechargement.
- `cancel(job_id) -> bool` : positionne un `threading.Event` associé au
  job ; `False` si `job_id` inconnu ou déjà terminé. L'arrêt effectif
  n'est pas instantané — il survient à la prochaine vérification (borne de
  bloc de copie, ou prochain appel du callback torf).
- Verrou (`threading.Lock`) protégeant le dict `job_id -> JobProgress` +
  le dict `job_id -> threading.Event`, même discipline que
  `gapscan_runner._lock`.
- **Nettoyage** : une tâche terminée (`done`/`error`/`cancelled`) reste
  dans le registre jusqu'à la fin du processus serveur (pas de purge
  automatique pour cette livraison — le volume de tâches reste faible,
  YAGNI ; à revisiter si ça devient un problème réel).

### `nfogen/file_staging.py` — copie par blocs + annulation

`stage_file`/`stage_files` gagnent des paramètres optionnels
`on_progress: Optional[Callable[[int, int], None]]` (appelé avec
`bytes_done, bytes_total`) et `cancel_event: Optional[threading.Event]`.

- Chemin **hardlink** (même volume) : instantané, un seul appel
  `on_progress(total, total)` — pas de découpage nécessaire.
- Chemin **copie** (repli `EXDEV`) : remplace `shutil.copy2` par une
  boucle de lecture/écriture par blocs de **16 Mio**, appelant
  `on_progress` après chaque bloc et vérifiant `cancel_event.is_set()` à
  chaque itération. `shutil.copystat` toujours appelé à la fin (métadonnées
  préservées, comme `copy2` le faisait).
- `OperationCancelled` (voir `nfogen/cancellation.py` ci-dessus) levée si
  annulé en cours de copie — le fichier partiel est supprimé avant de la
  propager (best-effort : un `OSError` pendant le nettoyage est
  journalisé, jamais masqué par une autre exception plus confuse).

### `nfogen/torrent_builder.py` — progression + annulation natives

`build_torrent` gagne `on_progress`/`cancel_event`, transmis à
`torf.Torrent.generate(callback=..., interval=1.0)` :

```python
def _callback(torrent, filepath, pieces_done, pieces_total):
    if cancel_event and cancel_event.is_set():
        return True  # torf : non-None => arrete le hachage
    if on_progress:
        on_progress(pieces_done, pieces_total)
```

`generate()` renvoie `False` si arrêté avant la fin — `build_torrent` lève
alors `OperationCancelled` (voir `nfogen/cancellation.py` ci-dessus,
partagée avec `file_staging.py` plutôt que dupliquée) — le fichier
`.torrent` partiel, s'il existe, n'est jamais écrit sur disque car
`torrent.write()` n'est appelé qu'après un `generate()` réussi).

### `nfogen/upload_prep.py` — `commit_upload` gagne des hooks

Même principe que `gapscan.py`/`gapscan_runner.py` : le module métier
(`upload_prep.py`) ne connaît PAS le type `JobState` de la couche
d'orchestration (`commit_job_runner.py` dépend déjà de `upload_prep.py`
pour `commit_upload` — lui faire connaître `JobState` en retour créerait
un import circulaire). `commit_upload` garde sa signature actuelle en
ajoutant deux paramètres optionnels en toute fin (`on_progress:
Optional[Callable[[str, float], None]] = None`, `cancel_event:
Optional[threading.Event] = None`) — `on_progress` reçoit un **nom
d'étape en texte brut** (`"staging"`, `"generating_nfo"`,
`"building_torrent"`, mêmes valeurs que `JobState`, mais comme simples
chaînes) et un pourcentage. `commit_job_runner.py` convertit ce nom en
`JobState(name)` pour mettre à jour son registre typé. Appelé
successivement avec `("staging", pct)` pendant la mise en scène,
`("generating_nfo", 0)` puis `("generating_nfo", 100)` autour de la
génération du `.nfo` (transition sans granularité propre, voir
Non-objectifs), `("building_torrent", pct)` pendant le hash. `commit_upload`
joue ici un rôle d'**adaptateur** : il convertit les callbacks bruts de
`file_staging.py` (`bytes_done, bytes_total`) et `torrent_builder.py`
(`pieces_done, pieces_total`) en pourcentages 0-100 avant de les relayer à
son propre `on_progress(step_name, percent)` — ni `file_staging.py` ni
`torrent_builder.py` ne savent qu'ils font partie d'une tâche suivie en
pourcentage nommé, ils exposent juste leurs compteurs bruts. Reste
directement appelable de façon 100% synchrone (comportement actuel
préservé) quand `on_progress`/`cancel_event` sont omis — **aucun test
existant de `commit_upload` ne casse**.

### `nfogen/api.py` — contrat de `/gapscan/prepare-upload/commit` change

`POST /gapscan/prepare-upload/commit` ne bloque plus : il appelle
`commit_job_runner.start(...)` et renvoie `{"job_id": "<uuid>"}`
immédiatement (changement cassant assumé — `UploadPrepPanel.tsx` est le
seul consommateur existant, pas de compatibilité à préserver).

Nouveaux endpoints (tous `Depends(require_token)`, comme le reste de
`/gapscan/*`) :
- `GET /gapscan/commit-jobs` → `list[JobProgress]` sérialisé
  (`commit_job_runner.list_jobs()`).
- `GET /gapscan/commit-jobs/{job_id}` → un seul job, 404 si inconnu.
- `POST /gapscan/commit-jobs/{job_id}/cancel` → 200 si annulation
  déclenchée, 404 si `job_id` inconnu, 409 si déjà terminé.

### Frontend

**`frontend/src/api/types.ts`/`client.ts`** :
- `CommitJobState = "staging" | "generating_nfo" | "building_torrent" | "done" | "error" | "cancelled"`
- `CommitJob { job_id, release_name, state, percent, started_at, finished_at, error, result }`
- `prepareUploadCommit(...)` renvoie désormais `Promise<{ job_id: string }>`
  (signature changée, tous les appelants mis à jour dans ce même plan).
- Nouveaux : `commitJobStatus(jobId)`, `listCommitJobs()`,
  `cancelCommitJob(jobId)`.

**`UploadPrepPanel.tsx`** : `handleConfirm` appelle `prepareUploadCommit`,
récupère `job_id`, démarre un polling (`setInterval`, 1500 ms — même
cadence que `GapScanPage.tsx` pour `gapscanStatus`) vers
`commitJobStatus(jobId)` jusqu'à un état terminal. Pendant `staging`/
`generating_nfo`/`building_torrent` : barre de progression + libellé
d'étape + bouton "Annuler" (appelle `cancelCommitJob`) à la place du
bouton Confirmer. À `done` : bascule sur l'affichage actuel
(`staged_path`/`torrent_path`/`nfo_path`, depuis `job.result`) et débloque
"Envoyer à C411" comme aujourd'hui. À `error`/`cancelled` : message
d'erreur, bouton Confirmer réapparaît (nouvelle tentative possible).

**Nouveau `frontend/src/components/ActiveTransfersTray.tsx`** : monté sur
`GapScanPage.tsx`, **indépendant** de l'état `activeUpload` (donc visible
même si aucun panneau n'est ouvert, et reconstruit après un rechargement
de page). Au montage : `listCommitJobs()` ; si au moins une tâche est
active, démarre son propre polling (même cadence). Affiche une ligne par
tâche (`release_name`, état, pourcentage, bouton Annuler si active) ;
replié/masqué s'il n'y a aucune tâche à afficher.

## Gestion des erreurs

- Erreur réelle pendant la copie/le hash (NAS déconnecté, disque plein…) :
  capturée dans le thread de la tâche (comme `gapscan_runner._run`), état
  `error` + message, jamais d'exception non gérée qui tue le thread
  silencieusement.
- Annulation : état `cancelled`, fichier(s) partiel(s) nettoyés au mieux
  (voir `file_staging.py` ci-dessus) — jamais de fichier à moitié copié
  laissé dans le dossier de mise en scène sans que l'état le signale.
- `job_id` inconnu (jamais existé, ou serveur redémarré depuis) : 404 sur
  les trois nouveaux endpoints — le frontend traite ça comme "tâche
  perdue", retire la ligne de l'encart sans planter.

## Tests

- `file_staging.py` : copie par blocs produit un fichier identique à
  l'ancien `shutil.copy2` (octets + métadonnées) ; `on_progress` appelé de
  façon croissante jusqu'à `bytes_total` ; `cancel_event` déjà positionné
  avant le premier bloc lève `OperationCancelled` et supprime le fichier
  partiel.
- `torrent_builder.py` : `on_progress` reçoit des couples croissants
  `(pieces_done, pieces_total)` ; `cancel_event` positionné fait lever
  `OperationCancelled`, aucun `.torrent` écrit sur disque.
- `upload_prep.commit_upload` : sans hooks, comportement 100% inchangé
  (tests existants) ; avec hooks, `on_progress` reçoit les trois étapes
  dans l'ordre.
- `commit_job_runner.py` : `start()` renvoie un `job_id` immédiatement
  (thread mocké/contrôlé dans le test) ; `status()` reflète l'état au fil
  du temps ; `list_jobs()` inclut les tâches terminées ; `cancel()` sur un
  job inconnu/déjà terminé renvoie `False`.
- `api.py` : `POST .../commit` renvoie `{job_id}` sans bloquer (mock du
  runner) ; `GET /gapscan/commit-jobs[/{id}]` et le `POST .../cancel`
  couvrent les cas 200/404/409.
- Frontend : `UploadPrepPanel` affiche la barre de progression pendant les
  états non terminaux, bascule sur le résultat à `done`, affiche l'erreur
  à `error`/`cancelled` ; `ActiveTransfersTray` liste les tâches actives et
  se met à jour au polling ; `client.test.ts` couvre les nouvelles
  fonctions.

## Points à vérifier pendant l'implémentation (pas bloquants, à documenter si ça diverge)

- Taille de bloc de copie (16 Mio proposé ci-dessus) : à ajuster si les
  tests réels sur le NAS de l'utilisateur montrent qu'une autre valeur
  est meilleure pour le débit — valeur arbitraire raisonnable, pas
  mesurée sur le matériel réel.
- `torf` `interval=1.0` (fréquence du callback) : évite un rafraîchissement
  excessif de l'état en mémoire lors du hachage d'un fichier de plusieurs
  Go (beaucoup de pièces) — ajustable si le suivi paraît trop lent/saccadé
  à l'usage réel.
