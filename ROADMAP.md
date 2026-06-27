# Roadmap nfogen

`nfogen` génère des fichiers NFO pilotés par des profils (C411 par défaut),
utilisable en CLI, en bibliothèque Python, en API HTTP, ou via le frontend
web. Ce document liste les idées futures — pour l'historique détaillé des
changements, voir `git log`.

## Décisions verrouillées

| Sujet | Décision |
|---|---|
| Frontend | Édite `rules.json` + templates des profils existants (catégories fixes). Pas de moteur de rendu inédit. |
| Stockage des profils | Fichiers sur disque (`NFOGEN_PROFILES_DIR`), un profil = un dossier. Export/import `.zip`. Pas de base de données. |
| Authentification | Token API simple (`NFOGEN_API_TOKEN`). À revoir pour un usage multi-utilisateurs (voir idées ci-dessous). |
| Stack frontend | React + Vite (SPA), consomme l'API FastAPI existante. |
| Déploiement | Repo unique (front + back) ; script natif Debian/Ubuntu (`scripts/install.sh`) en priorité, image Docker tout-en-un en option. |

## Idées / prochaines pistes

- **Droits d'accès multi-utilisateurs** (priorité actuelle) : génération de
  NFO ouverte à tous, gestion des profils réservée aux admins. Le token
  unique actuel ne distingue pas ces deux niveaux — il faudra des rôles
  (admin / standard), probablement plusieurs tokens ou de vrais comptes.
- CLI : pas d'équivalent des routes `/profiles/store*` (gérer un profil
  utilisateur sans passer par l'API).
- Pas de verrou sur les écritures concurrentes de `profile_store.py` (deux
  `PUT` simultanés sur le même profil) — à revisiter si l'usage multi-
  utilisateurs s'intensifie.
- Pas de tests automatisés pour le frontend.
- Extraction côté navigateur (sans upload) limitée à la catégorie vidéo ;
  audio/jeux/ebook/3D passent encore par l'upload classique.
- `name_proposal.py` : la saison/l'épisode restent déterminés en priorité
  par le nom de fichier (pas le tag `Title` embarqué) — à revoir si un tag
  contenant une numérotation différente est rencontré en pratique.
