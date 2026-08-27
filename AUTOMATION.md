# Automatisation upload — Du gap détecté au torrent en seed

Objectif de fond (formulé par l'utilisateur, 2026-08-27) : éliminer le
travail manuel entre "je remarque qu'un média manque sur le tracker" et
"il est en seed, uploadé". Contrainte de résilience : si C411 disparaît un
jour (comme ygg), seul un nouveau **profil** (règles + templates) doit
être à créer — le reste du pipeline (accès aux fichiers, génération,
détection de gap) doit rester agnostique du tracker.

Ce fichier documente la conception du pipeline complet ; `GAPSCAN.md`
documente la détection de gap elle-même (déjà livrée), ce fichier prend le
relais pour tout ce qui vient après.

## Décomposition et ordre (2026-08-27)

Projet trop large pour une seule conception : découpé en 7 sous-projets
indépendants, chacun avec son propre cycle conception → implémentation.
Ordre confirmé par l'utilisateur :

| # | Sous-projet | État |
|---|---|---|
| 1 | Accès NAS en lecture seule (résolution de chemins Sonarr/Radarr → chemin local) | Conception ci-dessous |
| 2 | Mise en scène du fichier (hardlink/copie) + génération du `.torrent` | À concevoir |
| 3 | `.torrent` + `.nfo` nommés correctement selon le profil | À concevoir |
| 4 | Upload vers C411 | À concevoir |
| 5 | Intégration qBittorrent (récupération du `.torrent` signé, mise en seed) | À concevoir |
| 6 | File d'attente un-par-un + email (succès/erreur) + règles de résolution automatique pilotées par le profil | À concevoir |
| 7 | Lidarr (musique) | Facultatif, en dernier |

## Décisions déjà prises (2026-08-27)

| Sujet | Décision |
|---|---|
| Fichier média source | **Jamais modifié, jamais déplacé/renommé.** Lecture seule stricte — le renommer casserait le suivi de chemin de Sonarr/Radarr/Lidarr ("film inexistant"). Seuls le `.torrent` et le `.nfo` (fichiers neufs) sont nommés selon la convention du tracker. |
| Où nfogen tourne vs où tournent Sonarr/Radarr | Pas forcément le même hôte/conteneur. Un mapping de chemins est nécessaire (voir sous-projet 1) — même principe que "Remote Path Mappings" dans Sonarr/Radarr eux-mêmes. |
| Hardlink vs copie | Détection **automatique** : tente `os.link()`, capture `EXDEV` (périphériques différents), bascule sur une copie dans ce cas. Pas besoin de déclarer la topologie à l'avance ; gère aussi une bibliothèque pas uniformément sur un seul montage. Option de forcer la copie manuellement conservée. |
| Seed à travers un lien lent (VPN site-to-site, etc.) | Explicitement écarté. Seul le transfert initial (une fois) peut passer par un lien lent ; jamais le service continu aux peers. |
| Génération du `.torrent` | Taille de pièce par barème (voir règles C411 ci-dessous), passkey jamais journalisée/exposée (même discipline que la clé API C411 dans `c411_client.py`), flags "seed immédiatement" + "tracker privé" obligatoires. |
| Upload | **Un par un, jamais en lot** — choix délibéré de l'utilisateur comme garde-fou, même si son rang C411 autoriserait le lot. |
| Après upload | C411 renvoie un `.torrent` **re-signé par eux** — c'est CE fichier-là qui doit être chargé dans qBittorrent pour seed, pas celui généré localement. |
| Email | Succès → minimal ("prêt à envoyer, confirme ?"), rien de plus. Erreur → détail complet de l'erreur inclus. |
| Résolution automatique de champs ambigus (ex. "French" générique → VFF) | Doit être pilotée par les règles du **profil** (pas de logique Python câblée en dur par tracker) — cohérent avec l'architecture existante (profils déclaratifs, cœur agnostique). Explicitement signalé comme le point le plus délicat par l'utilisateur ; pas résolu dans cette conception. |
| Lidarr | Confirmé voulu, mais explicitement facultatif — construit en dernier. |

### Règles C411 de création de torrent (copiées par l'utilisateur, 2026-08-27)

Barème taille de pièce (jamais "Auto" — un `.torrent` de plus de 16 Mo
risque d'être rejeté/mal géré) :

| Poids du fichier | Taille des pièces |
|---|---|
| < 1 Go | 1 Mo |
| < 2 Go | 2 Mo |
| < 3 Go | 4 Mo |
| < 8 Go | 8 Mo |
| > 8 Go | 16 Mo |

L'adresse d'annonce privée contient la passkey de l'utilisateur — aussi
sensible qu'une clé API, jamais à journaliser/exposer. Cocher "commencer à
seeder" + "tracker privé" à la création. Après soumission sur `/upload`
(catégorie + description, éventuellement auto-remplie par l'assistant TMDB
de C411), le torrent passe par une modération humaine ("Team Pending")
avant d'être public — atténue (sans l'annuler) le risque d'automatiser
cette étape.

## Sous-projet 1 : Accès NAS en lecture seule (résolution de chemins)

**But** : étant donné un fichier connu de Sonarr/Radarr (via leur API),
obtenir un chemin que le process nfogen peut réellement ouvrir en lecture
— que nfogen tourne sur la même machine qu'eux ou non.

**Constat** : `RadarrClient.list_movie_files()`/`SonarrClient.list_season_files()`
n'extraient aujourd'hui AUCUN chemin de fichier (`path`/`relativePath` des
API Radarr/Sonarr) — GapScan n'en a jamais eu besoin, seulement des
métadonnées de comparaison. Premier changement nécessaire : extraire ce
champ.

**Conception** :

1. **Extraction du chemin brut** : `RadarrMovieFile`/`SonarrSeasonFile`
   gagnent un champ `remote_path: Optional[str]` (`movieFile.path` /
   `episodeFile.path`, tel que rapporté par Sonarr/Radarr).
2. **Table de mapping, par connexion** (Sonarr et Radarr ont chacun la
   leur, comme leurs propres "Remote Path Mappings") : liste de paires
   `{remote_prefix, local_prefix}`, stockée dans `gapscan_config_store.py`
   (mêmes principes que l'existant : fichier JSON, `chmod 600`, `PUT`
   partiel). Vide par défaut = chemins identiques des deux côtés (cas
   swizzin actuel de l'utilisateur).
3. **Résolution** : préfixe le plus long de la table qui correspond au
   `remote_path`, substitué par le préfixe local correspondant. Sans
   correspondance dans la table (vide ou aucun préfixe ne matche) :
   `remote_path` est utilisé tel quel (comportement actuel implicite,
   déploiement à chemins identiques).
4. **Validation à chaque scan GapScan** (décision utilisateur, pas
   seulement au moment de préparer un upload) : après résolution, on
   vérifie que le chemin résolu existe et est lisible. Résultat exposé
   sur `GapResult` (nouveaux champs `local_path: Optional[str]`,
   `path_resolved: bool`, `path_error: Optional[str]`) — un mapping cassé
   se voit dès le scan suivant, pas seulement en pleine préparation d'un
   upload.
5. **Alternative écartée** : détection automatique du bon chemin local
   (recherche par taille/hash sur un répertoire racine configuré) — trop
   fragile (lent sur une grosse bibliothèque, ambigu en cas de fichiers de
   taille identique) pour un gain marginal face à une config manuelle que
   l'utilisateur maîtrise déjà via Sonarr lui-même.

**Pas encore tranché / pour la suite** : lecture effective du fichier
(ouverture, streaming pour le hash de pièces) appartient au sous-projet 2,
pas à celui-ci — le sous-projet 1 se limite à "obtenir et valider un
chemin local exploitable".

## Sous-projets 2 à 7 : non détaillés

À concevoir un par un, dans l'ordre du tableau ci-dessus, une fois le
sous-projet 1 implémenté.
