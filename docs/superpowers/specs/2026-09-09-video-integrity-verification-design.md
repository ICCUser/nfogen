# Vérification approfondie du fichier vidéo — design

## Contexte

Sous-projet 7 de la décomposition originale (AUTOMATION.md, "File
d'attente un-par-un + email + règles de résolution automatique") s'est
avéré regrouper 4 sous-systèmes assez indépendants : (1) vérification
approfondie du fichier vidéo, (2) règles de résolution automatique par
profil, (3) file d'attente "un par un", (4) email de notification.
Chacun aura son propre cycle spec → plan → implémentation. Ce document
couvre uniquement le (1), prérequis de sécurité des trois autres —
retour utilisateur, 2026-09-08/09 (brainstorm) : avant qu'un upload
puisse partir automatiquement (sous-projet à venir), il faut un filet
de sécurité qui garantisse "le maximum d'info sur le média" et que "le
media soit sûr de respecter les règles du profil/tracker" ; creusé plus
loin, la vraie demande est un contrôle **du fichier vidéo lui-même**
au-delà de ce que `pymediainfo` fournit aujourd'hui (`nfogen/extract.py`)
— un en-tête de conteneur valide n'exclut pas un flux corrompu au
milieu, une durée erronée (téléchargement tronqué), ou une
désynchronisation audio/vidéo.

Le flux d'upload manuel existant (Bibliothèque → "Préparer l'upload" →
"Confirmer" → "Créer un brouillon" / "Uploader directement") reste
inchangé pour les brouillons. Ce sous-projet ajoute une étape de
vérification **avant tout upload direct** (`POST /api/torrents`, part
réellement en modération) — jamais avant un brouillon, qui reste privé
tant que l'utilisateur ne le finalise pas lui-même.

## Objectif

Donner à nfogen la capacité de vérifier, avant un upload direct
(manuel aujourd'hui, automatique demain), que le fichier vidéo à
envoyer est réellement lisible de bout en bout, que sa durée réelle
correspond à celle annoncée, et que ses pistes audio/vidéo restent
synchronisées — un contrôle physique du fichier, complémentaire (pas un
doublon) des vérifications de conformité tracker déjà existantes
(catégorie/résolution/codec via `name_proposal.py`, groupe `blocked`).

## Hors périmètre (explicitement)

- **Conformité aux règles du profil/tracker** (résolution, codec,
  catégorie, nommage) : déjà couverte par `name_proposal.py` et le
  mécanisme `GroupProposal.blocked` existant. Ce sous-projet ne
  duplique pas cette logique.
- **Complétude des métadonnées de présentation** (TMDB manquant, pays
  absent, etc.) : `send_to_tracker()` dégrade déjà proprement ces
  champs (`presentation_warning`, jamais bloquant) — pas touché ici.
  Le filet de sécurité de ce sous-projet porte sur le **fichier**, pas
  sur la description générée.
- **Réparation automatique** d'un fichier détecté défaillant (aucune
  tentative de ré-encodage/réparation — signalement seulement).
- Le pipeline automatique lui-même (planification, file d'attente,
  règles de décision, email) : sous-projets suivants, qui consommeront
  `verify_video_integrity()` une fois disponible.

## Architecture — vue d'ensemble

```
Uploader directement (clic)
        │
        ▼
POST /gapscan/verify-integrity {staged_path}
        │  (nfogen/integrity_job_runner.py, tâche de fond)
        ▼
nfogen/video_integrity.py
   ├─ ffprobe  → durée/pistes annoncées par fichier
   └─ ffmpeg -v error -f null -  → décodage réel, détecte corruption
        │
        ▼
VideoIntegrityReport(passed, errors, warnings)
        │
   ┌────┴────┐
 passed    échec
   │          │
   ▼          ▼
POST /gapscan/prepare-upload/send   Bloqué : aucun brouillon ni upload,
   (comme aujourd'hui)              message d'erreur affiché
```

## A. `nfogen/video_integrity.py` (nouveau module)

### A.1 Structures de données

```python
@dataclass
class VideoIntegrityReport:
    passed: bool
    errors: list[str]
    warnings: list[str]
```

`errors` non vide ⇒ `passed = False` (bloquant). `warnings` n'affecte
jamais `passed` — réservé à des observations non bloquantes (ex. piste
avec un débit variable inhabituel) ; aucun warning de ce type n'est
émis dans la version initiale, le champ existe pour ne pas casser
l'interface le jour où un cas non bloquant apparaît.

### A.2 Vérification d'un seul fichier

```python
def verify_video_file(path: str) -> VideoIntegrityReport:
    """Verifie un seul fichier video : decode complet (corruption),
    duree reelle vs annoncee (troncature), desync audio/video.
    Necessite ffmpeg + ffprobe sur le PATH (voir has_ffmpeg())."""
```

Étapes internes :

1. **`ffprobe`** — récupère la durée et l'offset de départ
   (`start_time`) de chaque piste :
   ```
   ffprobe -v error -show_entries stream=codec_type,start_time,duration
           -show_entries format=duration -of json <path>
   ```
   Un `ffprobe` qui échoue (code retour non nul, JSON invalide) ⇒
   `VideoIntegrityReport(passed=False, errors=["Fichier illisible par ffprobe : <stderr>"], warnings=[])`
   immédiat — pas la peine de lancer le décodage complet sur un fichier
   qu'on ne sait même pas sonder.

2. **`ffmpeg` décodage complet** — détecte la corruption réelle :
   ```
   ffmpeg -v error -xerror -i <path> -map 0 -f null -
   ```
   Toute ligne sur stderr ⇒ ajoutée telle quelle à `errors` (préfixée
   `"Erreur de décodage : "`). Un code de sortie non nul sans sortie
   stderr exploitable ⇒ `"Décodage interrompu (code <N>)."`.

3. **Durée réelle vs annoncée** — compare `format.duration` (ffprobe,
   déclarée par le conteneur) à la durée du dernier timestamp
   effectivement décodé (obtenue via `-progress pipe:1` sur l'appel
   ffmpeg ci-dessus, champ `out_time_ms` de la dernière ligne de
   progression — réutilisé aussi pour le pourcentage d'avancement, voir
   B.2). Écart **> 5 secondes** ⇒
   `errors.append("Durée réelle (Xs) très inférieure à la durée annoncée (Ys) — fichier probablement tronqué.")`.
   Le seuil de 5s absorbe l'imprécision normale de fin de flux (dernier
   GOP incomplet, etc.) sans laisser passer une vraie troncature.

4. **Désynchronisation audio/vidéo** — compare `start_time` de la
   première piste vidéo à celui de la première piste audio (issus de
   l'étape 1). Écart **> 0.5 seconde** ⇒
   `errors.append("Décalage audio/vidéo détecté (Xs) au démarrage.")`.
   Une seule piste vidéo et une seule piste audio de référence sont
   comparées (la première de chaque type) — les pistes audio
   secondaires (VFF/VOST multiples) ne sont pas vérifiées
   individuellement dans cette première version.

### A.3 Vérification d'un groupe mis en scène

```python
def verify_staged_media(staged_path: str) -> VideoIntegrityReport:
    """staged_path peut etre UN fichier (film) ou UN dossier (serie /
    pack de saisons, voir upload_prep.CommitResult.staged_path) --
    enumere tous les fichiers video (memes extensions que
    extract.VIDEO_EXTS) et agrege un VideoIntegrityReport par fichier
    en un seul rapport global (union des errors/warnings, prefixee du
    nom de fichier concerne pour rester lisible sur un pack
    multi-saisons)."""
```

Si `staged_path` est un dossier, parcourt récursivement (`rglob`) —
nécessaire pour un pack de saisons (`S05/episode.mkv`, voir
sous-projet "Packs INTÉGRALE"). Un dossier sans aucun fichier vidéo
détecté ⇒ `errors=["Aucun fichier vidéo trouvé dans <staged_path>."]`
(cas anormal, jamais silencieux).

### A.4 Détection de la disponibilité de ffmpeg

```python
def has_ffmpeg() -> bool:
    """shutil.which('ffmpeg') is not None and shutil.which('ffprobe') is not None."""
```

Utilisée par le job runner (B) : si `ffmpeg`/`ffprobe` sont absents du
système, le job échoue immédiatement avec un message explicite
(`"ffmpeg/ffprobe requis pour la vérification — non trouvés sur le
serveur nfogen."`) plutôt que de laisser échouer chaque appel
`subprocess` un par un. **Jamais de dégradation silencieuse** : pas de
`ffmpeg` installé ⇒ pas d'upload direct possible, pas de contournement
automatique (cohérent avec "toujours vérifier avant un upload direct,
auto ou pas").

## B. `nfogen/integrity_job_runner.py` (nouveau module)

Même patron que `nfogen/commit_job_runner.py` (thread daemon,
`job_id` en mémoire, jamais persisté — une tâche interrompue par un
redémarrage du serveur est simplement perdue, comme les autres jobs de
fond du projet).

### B.1 États

```python
class IntegrityJobState(str, Enum):
    VERIFYING = "verifying"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"

@dataclass
class IntegrityJobProgress:
    job_id: str
    state: IntegrityJobState
    percent: float = 0.0
    started_at: float
    finished_at: Optional[float] = None
    result: Optional[dict] = None   # VideoIntegrityReport serialise (asdict)
    error: Optional[str] = None     # erreur d'execution (ffmpeg absent, exception) -- distinct de result.errors (echec de VERIFICATION)
```

`state = "done"` est atteint aussi bien pour un rapport `passed=True`
que `passed=False` — c'est `result["passed"]` qui porte le verdict,
pas l'état du job (même logique que `CommitJob` : le job "réussit" à
produire un résultat, que ce résultat soit positif ou négatif). `state
= "error"` est réservé à un problème d'exécution du job lui-même
(ffmpeg absent, exception Python inattendue) — distinction déjà
présente ailleurs dans le projet entre "la tâche a échoué" et "la
tâche a produit un résultat négatif".

### B.2 Progression

`ffmpeg -progress pipe:1 -nostats` (ajouté à la commande de décodage de
A.2 étape 2) émet des lignes `out_time_ms=<N>` sur stdout au fil du
décodage. Le job runner lit stdout ligne par ligne dans un thread,
calcule `percent = min(99, 100 * out_time_ms / duree_totale_annoncee)`
(la durée totale vient de l'étape ffprobe, connue avant de lancer le
décodage) et met à jour `IntegrityJobProgress.percent`. Plafonné à 99%
pendant le décodage — 100% seulement une fois le job effectivement
`DONE` (évite un affichage "100%" pendant que les vérifications de
cohérence post-décodage tournent encore).

### B.3 API du module

```python
def start(staged_path: str) -> str:            # renvoie job_id, leve RuntimeError si has_ffmpeg() est faux
def status(job_id: str) -> IntegrityJobProgress
def cancel(job_id: str) -> None                 # meme patron que commit_job_runner.cancel
```

## C. API HTTP (`nfogen/api.py`)

Nouveaux endpoints, même patron que les `commit-jobs` existants :

```python
class VerifyIntegrityRequest(BaseModel):
    staged_path: str

@app.post("/gapscan/verify-integrity", dependencies=[Depends(require_token)])
def gapscan_verify_integrity(req: VerifyIntegrityRequest) -> dict:
    # leve HTTPException(400) si has_ffmpeg() est faux (message explicite)
    job_id = integrity_job_runner.start(req.staged_path)
    return {"job_id": job_id}

@app.get("/gapscan/integrity-jobs/{job_id}", dependencies=[Depends(require_token)])
def gapscan_integrity_job_status(job_id: str) -> dict: ...

@app.post("/gapscan/integrity-jobs/{job_id}/cancel", dependencies=[Depends(require_token)])
def gapscan_cancel_integrity_job(job_id: str) -> dict: ...
```

## D. Frontend

### D.1 `frontend/src/api/client.ts`

```typescript
export function verifyIntegrity(stagedPath: string): Promise<{ job_id: string }>
export function integrityJobStatus(jobId: string): Promise<IntegrityJob>
export function cancelIntegrityJob(jobId: string): Promise<void>
```

`IntegrityJob` (nouveau type, `frontend/src/api/types.ts`) :
```typescript
export interface IntegrityJob {
  job_id: string;
  state: "verifying" | "done" | "error" | "cancelled";
  percent: number;
  result: { passed: boolean; errors: string[]; warnings: string[] } | null;
  error: string | null;
}
```

### D.2 `UploadPrepPanel.tsx`

`handleSend(index, direct)` : quand `direct === true` UNIQUEMENT (le
chemin brouillon, `direct === false`, reste strictement inchangé — ni
appel ni délai supplémentaire), avant l'appel existant à
`sendToTracker()` :

1. `verifyIntegrity(commit.staged_path)` → `job_id`.
2. Poll (même mécanisme `pollRefs`/`setInterval` déjà utilisé pour les
   `CommitJob`, généralisé à un second `Record<number, ...>` d'état
   pour ne pas entrer en collision avec le polling de `Confirmer`) —
   affiche une barre de progression avec le libellé "Vérification du
   fichier…".
3. Job `done` avec `result.passed === true` → enchaîne automatiquement
   sur l'appel `sendToTracker()` existant, sans action utilisateur
   supplémentaire.
4. Job `done` avec `result.passed === false` → affiche
   `result.errors` en rouge (même style que les `warnings` de groupe
   existants), **n'appelle jamais `sendToTracker()`**, le bouton
   "Uploader directement" redevient cliquable (permet de relancer après
   correction du fichier source, ex. re-téléchargement via Sonarr puis
   nouveau "Confirmer").
5. Job `error` (ffmpeg absent, exception) → affiche `error` en rouge,
   même comportement bloquant que 4.

Le bouton "Créer un brouillon" n'est jamais désactivé ni retardé par ce
mécanisme.

## E. Dépendance système

`ffmpeg` (fournit aussi `ffprobe`) ajouté :
- **`Dockerfile`** : `apt-get install -y --no-install-recommends ffmpeg`
  aux côtés de `libmediainfo0v5` déjà présent.
- **`README.md`**, section Installation : ligne équivalente pour une
  installation manuelle (hors Docker).

Déjà présent sur les runners GitHub Actions (`ubuntu-latest` embarque
`ffmpeg` nativement) — aucun changement requis dans
`.github/workflows/ci.yml` pour que les tests s'exécutent réellement
en CI (voir Tests ci-dessous).

## Gestion d'erreur — résumé

| Situation | `passed` | Résultat |
|---|---|---|
| Décodage propre, durée cohérente, A/V synchro | `True` | Upload direct enchaîné automatiquement |
| Erreur de décodage (corruption) sur stderr ffmpeg | `False` | Bloqué, aucun brouillon ni upload |
| Durée réelle < durée annoncée − 5s | `False` | Bloqué, aucun brouillon ni upload |
| Désync A/V > 0.5s au démarrage | `False` | Bloqué, aucun brouillon ni upload |
| `ffprobe` échoue à sonder le fichier | `False` | Bloqué, aucun brouillon ni upload |
| `ffmpeg`/`ffprobe` absents du serveur | job `error` | Bloqué, message explicite, aucun contournement |
| Utilisateur annule pendant la vérification | job `cancelled` | Aucun appel à `sendToTracker()` |

## Tests

Même patron que `tests/test_c411.py` (`HAS_FFMPEG`/`HAS_MEDIAINFO`,
clip synthétique généré via `ffmpeg -f lavfi`) :

- `tests/test_video_integrity.py` :
  - Tests unitaires **mockés** (`monkeypatch` sur `subprocess.run`,
    comme le reste du projet mocke `pymediainfo`) pour la logique pure
    (parsing JSON ffprobe, calcul d'écart de durée/désync, agrégation
    multi-fichiers dans `verify_staged_media`) — s'exécutent toujours,
    sans ffmpeg réel.
  - Tests d'intégration **réels**, `@pytest.mark.skipif(not HAS_FFMPEG, ...)`,
    sur un clip synthétique généré à la volée (`ffmpeg -f lavfi
    -i testsrc -f lavfi -i sine ...`) : un cas propre (`passed=True`),
    un cas tronqué (fichier coupé à la moitié de ses octets après
    génération, simule un téléchargement incomplet), un cas corrompu
    (quelques octets aléatoires écrasés au milieu du fichier).
- `tests/test_integrity_job_runner.py` : même style que
  `tests/test_commit_job_runner.py` existant (mock de
  `video_integrity.verify_staged_media`, vérifie la progression/l'état
  du job, l'annulation).
- `tests/test_api.py` : nouveaux tests pour les 3 endpoints (mock du
  job runner, comme les tests existants de `/gapscan/commit-jobs/*`).
- Frontend : `UploadPrepPanel.test.tsx` — nouveaux tests pour le
  polling de vérification avant upload direct (succès enchaînant sur
  `sendToTracker`, échec bloquant avec affichage des erreurs, jamais
  déclenché pour "Créer un brouillon").
