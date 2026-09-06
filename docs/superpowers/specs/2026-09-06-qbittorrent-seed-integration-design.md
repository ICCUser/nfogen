# Intégration qBittorrent — mise en seed après upload (sous-projet 6)

**Statut** : approuvé par l'utilisateur (2026-09-06), prêt pour le plan d'implémentation.

## Problème

Après qu'un brouillon C411 (sous-projet 5) soit finalisé et approuvé par
la modération, le tracker délivre un `.torrent` **re-signé** — c'est CE
fichier-là (et lui seul) qui doit être chargé dans un client de seed,
jamais celui généré localement (décision déjà actée, voir "Décisions
déjà prises"). Aujourd'hui rien n'existe pour l'ajouter automatiquement à
un client de seed : l'utilisateur doit le faire entièrement à la main,
en retrouvant lui-même le contenu déjà mis en scène par nfogen.

**Point vérifié en conditions réelles (2026-09-06)** : le fichier
re-signé se télécharge depuis
`GET https://c411.org/api/torrents/{infoHash}/download`. Testé avec la
clé API Bearer du compte (même mécanisme que le reste de l'API C411) :
réponse `302` vers `/login?redirect=...` — **cet endpoint exige une
session navigateur authentifiée, pas la clé API**. Aucune automatisation
de la récupération n'est donc possible sans reproduire un login complet
(hors de portée de ce projet, jamais fait ailleurs dans nfogen). La
récupération du fichier re-signé reste donc **manuelle** : l'utilisateur
le télécharge lui-même depuis son navigateur, puis le donne à nfogen.

## Objectifs

- Un endroit pour déposer le `.torrent` re-signé une fois téléchargé
  manuellement, sans avoir à retrouver soi-même le chemin de mise en
  scène correspondant.
- nfogen l'ajoute au client de seed (qBittorrent) en le pointant sur le
  contenu **déjà mis en scène** (`staging_dir`) — jamais un nouveau
  transfert, jamais un nouveau téléchargement.
- Le flux reste utilisable même **longtemps après** le "Confirmer"
  d'origine (la modération C411 n'est pas immédiate) : le chemin de mise
  en scène doit survivre à un redémarrage du serveur nfogen.

## Non-objectifs (hors scope, YAGNI)

- Récupération automatique du `.torrent` re-signé — impossible sans
  automatiser un login navigateur (voir ci-dessus), écarté.
- Nettoyage automatique du dossier de mise en scène après ajout au seed
  — une fois ajouté à qBittorrent, c'est lui qui "possède" ce contenu du
  point de vue de l'utilisateur ; un nettoyage éventuel reste une action
  manuelle côté qBittorrent (retirer le torrent + supprimer les données),
  pas un automatisme nfogen (retour utilisateur, 2026-09-06 : risque réel
  de casser un seed en cours si nfogen se trompait).
- Support Transmission — uniquement qBittorrent pour ce sous-projet
  (nommé ainsi dans la décomposition depuis le départ) ; le même patron
  (`*_client.py` httpx, config globale) resterait réutilisable si
  Transmission est demandé plus tard.
- Plusieurs instances/comptes qBittorrent — une seule configuration
  globale, comme Sonarr/Radarr.
- Vérification que le fichier déposé correspond bien au bon titre
  (infoHash, nom...) — si l'utilisateur se trompe de fichier, qBittorrent
  lui-même signalera une erreur de contenu manquant/différent au premier
  hash-check ; pas de vérification stricte côté nfogen (cohérent avec
  "jamais deviner" — nfogen ne devine pas non plus une erreur possible).

## Architecture

### Nouveau module : `nfogen/qbittorrent_client.py`

Même patron httpx que `radarr_client.py`/`sonarr_client.py` (lecture/
écriture minimale, aucune dépendance croisée) :

```python
class QBittorrentError(RuntimeError):
    """Erreur reseau, authentification ou reponse inattendue de l'API qBittorrent."""


class QBittorrentClient:
    def __init__(self, base_url: str, username: str, password: str,
                 http_client: Optional[httpx.Client] = None, timeout: float = 30.0) -> None: ...

    def close(self) -> None: ...

    def add_torrent(self, torrent_bytes: bytes, save_path: str, filename: str = "release.torrent") -> None:
        """Se connecte au besoin (POST /api/v2/auth/login, cookie de
        session conserve par le client httpx), puis ajoute le .torrent
        DEJA TELECHARGE (voir "Problème") via POST /api/v2/torrents/add
        (multipart, champ "torrents" + "savepath"). `save_path` doit deja
        contenir le contenu correspondant -- jamais retelecharge par ce
        module, seulement verifie/seede par qBittorrent lui-meme."""
```

`save_path` = le **parent** du `staged_path` connu (voir plus bas) : pour
un fichier unique (`staging_dir/release_name.ext`), c'est `staging_dir`
lui-même ; pour un pack (`staging_dir/release_name/`), c'est également
`staging_dir` (le dossier `release_name/` est déjà le nom interne
attendu par le `.torrent`). Le nom de fichier/dossier interne du
`.torrent` re-signé doit correspondre exactement à ce qui a été mis en
scène — **point à vérifier en conditions réelles** : rien ne garantit que
C411 ne renomme jamais rien en re-signant (comme pour tout ce qui touche
au comportement exact du tracker, à confirmer avec un vrai fichier avant
de considérer ce sous-projet pleinement fiable).

### `nfogen/gapscan_config_store.py` — configuration qBittorrent

Nouveaux champs globaux (comme Sonarr/Radarr, pas namespacés par
profil — un seul client de seed, indépendant du tracker utilisé) :
`qbittorrent_url`, `qbittorrent_username`, `qbittorrent_password`, avec
repli sur les variables d'environnement `NFOGEN_QBITTORRENT_URL`/
`_USERNAME`/`_PASSWORD` (même patron que `effective_sonarr()`). `write()`
gagne ces 3 mêmes paramètres optionnels (`PUT /gapscan/config` peut donc
les définir, comme pour Sonarr/Radarr). Nouvelle fonction
`effective_qbittorrent() -> Optional[tuple[str, str, str]]` ((url,
username, password), `None` si l'un des trois manque). `status()` gagne
`qbittorrent_configured`/`qbittorrent_url` (jamais le mot de passe).

### `nfogen/upload_history_store.py` — retrouver le contenu mis en scène

`record()` gagne un paramètre optionnel `staged_path: Optional[str] = None`,
stocké dans l'entrée `kind` correspondante quand fourni :

```python
def record(key: tuple, *, kind: str, release_name: str,
           at: Optional[float] = None, staged_path: Optional[str] = None) -> None: ...
```

`commit_job_runner.py` passe désormais `staged_path=result.staged_path`
à son appel `record(key, kind="committed", ...)` — c'est la SEULE entrée
qui connaît ce chemin (celle produite juste après la mise en scène).

Nouvelle fonction `pending_seed_entries() -> list[dict]` : parcourt le
fichier JSON et renvoie, pour chaque clé ayant une entrée `"sent"` mais
**pas** d'entrée `"seeding"`, un dict `{"key": <chaîne opaque>,
"media_type": "movie"|"series", "release_name": str,
"staged_path": str | None, "sent_at": float | None}` (`media_type`
déduit directement du premier élément de la clé décodée, ex.
`["movie", 42]`). `staged_path` peut être `None` pour une entrée
enregistrée avant l'ajout de ce champ — géré côté API (voir plus bas).

### `nfogen/api.py`

- `GapscanConfigWriteRequest` (déjà existant, `PUT /gapscan/config`)
  gagne `qbittorrent_url`/`qbittorrent_username`/`qbittorrent_password`
  (optionnels, transmis tels quels à `gapscan_config_store.write()`).
- **`GET /gapscan/seed-queue`** (nouveau) — renvoie
  `upload_history_store.pending_seed_entries()` tel quel.
- **`POST /gapscan/seed-queue/add`** (nouveau, `multipart/form-data`,
  champs `key` + `torrent` fichier) — construit `QBittorrentClient`
  depuis `gapscan_config_store.effective_qbittorrent()` (400 si absent),
  retrouve l'entrée correspondant à `key` dans `pending_seed_entries()`
  (404 si inconnue/déjà ajoutée), 400 si `staged_path` est `None`
  (entrée trop ancienne, avant ce champ — message explicite plutôt que
  deviner un chemin), calcule `save_path = str(Path(staged_path).parent)`,
  appelle `add_torrent(...)`, puis
  `upload_history_store.record(decoded_key, kind="seeding", release_name=...)`.
  Erreur `QBittorrentError` → 400 avec message clair.

### Frontend

**Nouvelle page `SeedQueuePage.tsx`** (`/seed-queue`), lien de nav
"À mettre en seed" à côté de "Bibliothèque" :
- Liste les entrées de `GET /gapscan/seed-queue` (release_name, date
  d'envoi à C411).
- Pour chaque ligne : un input fichier ("Choisir le .torrent re-signé")
  + bouton "Ajouter au client de seed" — envoie `POST
  /gapscan/seed-queue/add` (multipart), retire la ligne de la liste une
  fois réussi (ou affiche l'erreur sinon, sans la retirer).
- `client.ts` : `seedQueue(): Promise<SeedQueueEntry[]>`,
  `addToSeedQueue(key: string, file: File): Promise<{status: string}>`.
- `types.ts` : `SeedQueueEntry { key, media_type, release_name,
  staged_path, sent_at }`.
- Formulaire de configuration qBittorrent (URL, utilisateur, mot de
  passe) — ajouté au panneau de configuration déjà présent sur
  `LibraryPage.tsx` (Sonarr/Radarr/tracker), pas une page séparée.
  `types.ts` : `GapscanConfig` gagne `qbittorrent_configured`/
  `qbittorrent_url` ; `GapscanConfigWrite` gagne `qbittorrent_url`/
  `qbittorrent_username`/`qbittorrent_password`.

## Gestion des erreurs

- qBittorrent non configuré → 400 explicite avant tout appel réseau.
- Connexion/authentification qBittorrent échouée → `QBittorrentError`
  claire (jamais un plantage silencieux), remontée en 400.
- Clé de file d'attente inconnue ou déjà traitée (doublon de clic,
  entrée déjà marquée `seeding` par un autre onglet) → 404.
- `staged_path` manquant (entrée enregistrée avant ce champ) → 400 avec
  message explicite, pas de suppositions.
- Écriture de `upload_history_store` (marquage `seeding`) échoue → même
  discipline que `record()` existant : jamais propagée, un ajout
  qBittorrent par ailleurs réussi ne doit pas échouer pour autant.

## Tests

- `qbittorrent_client.py` : login réussi/échoué, `add_torrent` (mock
  HTTP, même patron `radarr_client.py`/`sonarr_client.py`), erreurs
  réseau → `QBittorrentError`.
- `gapscan_config_store.py` : `effective_qbittorrent()` (fichier, repli
  environnement, absent), `status()` inclut les nouveaux champs.
- `upload_history_store.py` : `record(..., staged_path=...)` persiste et
  se relit ; `pending_seed_entries()` (inclut "sent" sans "seeding",
  exclut "seeding" déjà présent, `staged_path` `None` géré, décodage de
  `media_type` depuis la clé).
- `commit_job_runner.py` : `staged_path` transmis à `record()` sur
  `JobState.DONE`.
- `api.py` : `GET /gapscan/seed-queue` (liste, vide) ; `POST
  .../add` (succès, 400 sans config, 404 clé inconnue, 400 staged_path
  manquant, 400 sur `QBittorrentError`).
- Frontend : `SeedQueuePage` (rendu de la liste, upload de fichier,
  appel API, retrait de la ligne après succès, affichage d'erreur sinon).

## Points à vérifier pendant l'implémentation (pas bloquants)

- Le nom de fichier/dossier interne du `.torrent` re-signé par C411
  correspond-il exactement à celui mis en scène par nfogen (aucun
  renommage côté tracker) ? À confirmer avec un vrai fichier re-signé
  avant de considérer ce sous-projet pleinement fiable en production.
- Format exact de la réponse de succès de l'API qBittorrent (`"Ok."` en
  texte brut pour login et add) — documenté ainsi par l'API officielle
  qBittorrent v2, jamais vérifié directement par ce projet avant
  aujourd'hui.
