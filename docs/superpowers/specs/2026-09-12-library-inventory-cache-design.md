# Cache local de l'inventaire Bibliothèque — Design

## Contexte et problème

La page Bibliothèque (`/library`) dépend aujourd'hui de Radarr/Sonarr
joignables **en direct** à chaque chargement : `gapscan_library.list_library()`
appelle `radarr.list_movie_files()` / `sonarr.list_season_files()` à chaque
requête. Le fix "single-flight" (`nfogen/api.py:_cached_library_items()`,
livré plus tôt cette session) évite les appels concurrents dupliqués, mais
ne supprime pas la dépendance réseau elle-même : chaque chargement de page
reste conditionné à la disponibilité de Radarr/Sonarr au moment du clic.

**Idée retenue (utilisateur, 2026-09-12)** : persister une copie locale de
l'inventaire de base (titre/année/qualité/taille/added_at) et la
synchroniser périodiquement en tâche de fond, pour que l'AFFICHAGE de la
Bibliothèque soit instantané et indépendant de la disponibilité de
Radarr/Sonarr au moment du clic.

## Périmètre (confirmé explicitement, à ne pas élargir sans revalider)

Uniquement l'affichage/chargement de la liste. Toute action (Préparer
l'upload, Confirmer, envoi C411...) continue d'aller chercher les données
**en direct** (copie, hardlink, scan MediaInfo poussé) — jamais de
changement là-dessus, cohérent avec la règle déjà établie cette session
("le garde-fou doit exister dans tous les cas", voir
`nfogen-automation-pipeline-vision` en mémoire).

## Contexte technique existant (réutilisé, pas redérivé)

- `nfogen/gapscan_library.py:list_library(radarr=None, sonarr=None,
  previous_results=None, profile="c411")` : fusionne l'inventaire
  Radarr/Sonarr de base avec le statut C411 (`previous_results`, des
  `GapResult` persistés). L'inventaire de base ne vient aujourd'hui QUE de
  l'appel live.
- `nfogen/gapscan_results_store.py` : persistance JSON existante pour
  `list[GapResult]` (statut/correspondances C411 uniquement, pas
  l'inventaire de base). Réécriture complète à chaque `save()`. 8,9 Mo
  actuellement (mesuré en conditions réelles), jugé négligeable à ce
  volume.
- `nfogen/gapscan_runner.py` : le SCAN (comparaison C411) est déjà
  incrémental, mais c'est un flux distinct de `list_library()`, qui sert
  directement la page Bibliothèque et reste 100% live côté Radarr/Sonarr.

## Décisions de cadrage

1. **Persistance séparée** : un nouveau store dédié
   (`library_inventory_store.py`), distinct de `gapscan_results_store.py`
   — ces deux données ont des rythmes de vie et des responsabilités
   différents (inventaire local vs statut tracker), les mélanger romprait
   la séparation déjà existante dans le code.
2. **Déclencheurs de synchro** : les trois combinés — intervalle fixe en
   tâche de fond, une première passe immédiate au démarrage du service, et
   un bouton "Rafraîchir" manuel dans l'UI. Un seul chemin de code
   (`sync_now()`) pour les trois, jamais de logique dupliquée.
3. **Tolérance à la panne** : la Bibliothèque affiche toujours la dernière
   copie locale connue, même périmée, plutôt que de planter ou se vider.
   Un indicateur "dernière synchro : il y a X" informe l'utilisateur de la
   fraîcheur des données.
4. **Premier démarrage** (aucune synchro n'a jamais réussi) : repli
   exceptionnel sur un appel live unique, pour amorcer le cache sans
   afficher une page vide.

## Architecture et flux de données

```
Démarrage service ─┐
Intervalle fixe ────┼──▶ library_sync_runner.sync_now() ──▶ gapscan_library.list_library(radarr, sonarr, previous_results)
Bouton "Rafraîchir"─┘         (verrouillé : une seule                   │
                                synchro à la fois)                       ▼
                                                          library_inventory_store.save(items, synced_at)
                                                                          │
GET /gapscan/library ───────────────────────────────────────────────────┘
   lit library_inventory_store.load() (instantané, local)
   si jamais synchronisé : repli EXCEPTIONNEL sur un appel live une seule fois (auto-amorce le cache)
```

`sync_now()` réutilise **tel quel** `gapscan_library.list_library()` — pas
de logique de fusion à dupliquer, on persiste directement son résultat déjà
calculé. `GET /gapscan/library` ne fait donc plus aucun appel Radarr/Sonarr
direct en fonctionnement normal.

## Composants

1. **`nfogen/library_inventory_store.py`** (nouveau) — même patron que
   `gapscan_results_store.py` (JSON, `save()`/`load()`, jamais bloquant si
   absent/corrompu) : persiste `list[LibraryItem]` + `synced_at` +
   `last_attempt_at`/`last_attempt_error` (voir Gestion d'erreur).
   Réutilise directement les dataclasses existantes (`LibraryItem`,
   `ReleaseQuality`).

2. **`nfogen/library_sync_runner.py`** (nouveau) :
   - `start(interval_seconds)` : lance un thread daemon au démarrage du
     service, fait une première synchro immédiate puis boucle
     (`sync_now()` → `sleep(interval)` → répète).
   - `sync_now()` : construit les clients Radarr/Sonarr (même logique
     qu'aujourd'hui), calcule le nouvel inventaire en mémoire via
     `gapscan_library.list_library(...)`, puis seulement en cas de succès
     appelle `library_inventory_store.save(...)`.
   - Un `threading.Lock` non bloquant empêche deux synchros concurrentes —
     un déclenchement pendant qu'une synchro tourne déjà est simplement
     ignoré (jamais mis en file, jamais bloquant pour l'appelant).

3. **`GET /gapscan/library`** (modifié) : lit
   `library_inventory_store.load()`. Si jamais synchronisé : un appel live
   exceptionnel unique pour amorcer le cache. La réponse inclut
   `synced_at` pour l'indicateur de fraîcheur.

4. **`POST /gapscan/library/refresh`** (nouveau) : déclenche `sync_now()`
   et attend la fin (quelques secondes — un simple appel liste
   Radarr/Sonarr, pas un scan MediaInfo lourd) avant de répondre. C'est le
   bouton "Rafraîchir".

5. **Config** : `NFOGEN_LIBRARY_SYNC_INTERVAL_SECONDS` (défaut : 900s /
   15 min), même convention que les autres réglages `NFOGEN_*` existants.

## Gestion d'erreur

Règle centrale : **une synchro qui échoue ne doit jamais écraser une copie
locale valide.** `sync_now()` calcule le nouvel inventaire en mémoire
d'abord ; ce n'est qu'une fois le calcul terminé avec succès qu'il appelle
`library_inventory_store.save(...)`. Si Radarr/Sonarr lèvent une
exception : on l'attrape, on logge, et on n'écrit rien — le fichier reste
tel qu'il était après la dernière synchro réussie.

Le store garde deux horodatages distincts :
- `synced_at` : dernière synchro **réussie**.
- `last_attempt_at` / `last_attempt_error` : dernière tentative, réussie ou
  non — pour qu'un "Rafraîchir" qui échoue affiche un message clair
  ("Échec de la dernière synchronisation à 14h32 : Radarr injoignable —
  affichage des données d'il y a 20 min") plutôt qu'un échec silencieux.

Tout premier démarrage sans aucune synchro réussie : si l'appel live
exceptionnel échoue aussi, la Bibliothèque affiche une liste vide avec un
message explicite ("Impossible de joindre Radarr/Sonarr pour la
synchronisation initiale") — jamais de crash de page.

## Tests

1. **`tests/test_library_inventory_store.py`** (nouveau) : aller-retour
   save/load, fichier absent → `None`, fichier corrompu → `None` (jamais
   d'exception), non configuré → no-op.

2. **`tests/test_library_sync_runner.py`** (nouveau) :
   - `sync_now()` appelle `list_library()` avec les bons clients +
     `previous_results`, puis sauvegarde le résultat.
   - Un échec (Radarr/Sonarr lèvent une exception) n'appelle jamais
     `save()` — la copie existante reste intacte, `last_attempt_error` est
     renseigné.
   - Le verrou empêche deux `sync_now()` concurrents.

3. **`tests/test_api.py`** (mis à jour) — test le plus important, celui
   qui prouve que le problème initial est réglé :
   - `GET /gapscan/library` avec un cache déjà rempli → zéro appel à
     Radarr/Sonarr (mock qui lève une exception si appelé, pour le
     garantir).
   - Cache vide (premier démarrage) → un seul appel live exceptionnel, qui
     remplit le cache.
   - `POST /gapscan/library/refresh` → déclenche une synchro et renvoie le
     nouveau `synced_at`.
