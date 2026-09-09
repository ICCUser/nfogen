# Refonte UI/UX (largeur, tri de tableau, pagination, suivi seed live) — design

## Contexte

Retour utilisateur (2026-09-09), après la résolution des problèmes de
performance de la Bibliothèque : la demande UI/UX initiale ("l'interface
est trop concentrée") n'avait été traitée qu'en partie (repositionnement
de `UploadPrepPanel` en modal). Reste, cité explicitement :

> "Pour les tableaux, j'avais en tête du dynamique [...] datatable [...]
> pas fluide. En cours de seed il faut rafraîchir la page pour avoir un
> aperçu, [...] le plus intéressant est d'avoir en live la colonne envoi
> qui s'adapte en direct. Les tableaux sont trop longs [...]. Les pages
> de tableau, notamment la bibliothèque, ne permettent pas un retour à la
> première page directement. [...] utiliser un peu plus la pleine largeur
> [...]. Une réorganisation dans la page réglages ne serait pas de refus
> [...] c'est le foutoir [...] la pleine largeur n'est pas utilisée."

## Constat (code existant)

- `frontend/src/App.tsx` : `<main className="mx-auto max-w-7xl px-4 py-6">`
  contraint TOUTE l'application (~1280px max), quelle que soit la largeur
  d'écran réelle.
- `frontend/src/pages/SettingsPage.tsx` : conteneur racine
  `<div className="max-w-lg space-y-6">` (~512px) — une contrainte
  SUPPLÉMENTAIRE et locale, en plus de celle d'`App.tsx`. 4 sections
  empilées verticalement (Connexion, Authentification, Comptes
  administrateurs, Configuration globale Sonarr/Radarr/qBittorrent/TMDB —
  cette dernière déjà repliable).
- `frontend/src/pages/LibraryPage.tsx` : `<table>` HTML brut, 7 colonnes
  fixes, aucun tri (ni clic d'en-tête, ni paramètre backend). Pagination
  Précédent/Suivant uniquement (`page <= 1` / `page * PAGE_SIZE >= total`,
  `PAGE_SIZE = 50`), affichée UNE SEULE fois sous le tableau — aucun moyen
  de revenir directement à la page 1 sans cliquer "Précédent" en boucle.
- `nfogen/api.py` `GET /gapscan/library` : filtre en mémoire (q, media_type,
  genre, tracker_genre, status, added_since_days, processed) puis pagine
  (`items[start:start+page_size]`) — **aucun tri**, l'ordre est celui
  renvoyé par `gapscan_library.list_library()` (ordre Radarr puis Sonarr,
  non spécifié).
- `frontend/src/pages/SeedQueuePage.tsx` : `loadSeedStatus()` (torrents en
  cours, dont la colonne "Envoi" = vitesse d'upload) n'est appelé qu'une
  fois au montage (`useEffect(..., [])`) — jamais rafraîchi automatiquement,
  confirmant le "il faut rafraîchir la page" du retour utilisateur.
- Précédent similaire déjà dans le projet : `LibraryPage.tsx`
  `pollSeedMatchUntilTerminal()` fait déjà un `setInterval` de polling sur
  un job en cours — même patron à réutiliser pour `SeedQueuePage`.

## Décisions actées (questions posées à l'utilisateur, 2026-09-09)

- **Portée du tri** : sur toute la bibliothèque (avant pagination), pas
  seulement la page affichée — nécessite un paramètre de tri côté backend.
- **Bibliothèque de tableau** : [TanStack Table](https://tanstack.com/table)
  (`@tanstack/react-table`, ex-`react-table`) — headless (aucun style
  imposé, garde le Tailwind existant), gère tri/état de colonnes sans
  dicter le rendu.
- **Réglages** : grille en 2 colonnes plutôt qu'une barre latérale (4
  sections seulement — une nav dédiée ajouterait des clics pour peu de
  contenu).
- **Largeur** : conteneur global élargi dans `App.tsx`, profite à toutes
  les pages (pas seulement Bibliothèque/Réglages).

## A. Largeur pleine page

`App.tsx` : `max-w-7xl` (1280px) → `max-w-[1600px]`. Valeur choisie pour
rester confortable sur un très grand écran (au-delà, des lignes de texte
larges de plusieurs centaines de caractères nuiraient à la lecture) tout
en libérant nettement plus d'espace que 1280px. `px-4` conservé (marge
latérale minimale).

`SettingsPage.tsx` : `max-w-lg` (512px) sur le conteneur racine supprimé
— la page utilise alors toute la largeur laissée par `App.tsx`, à
combiner avec la grille 2 colonnes (section E) pour ne pas se retrouver
avec des champs de formulaire étirés sur 1600px de large (illisible).

## B. Tri de tableau (TanStack Table + tri serveur)

**Backend** (`nfogen/api.py`, `GET /gapscan/library`) : deux nouveaux
paramètres de requête, `sort` et `order`.

- `sort` : un identifiant de colonne parmi `title`, `media_type`,
  `status`, `team`, `quality`, `added_at`. Absent/inconnu → comportement
  actuel inchangé (ordre de `list_library()`).
- `order` : `asc` (défaut) ou `desc`.
- Le tri s'applique sur `items` **avant** la troncature de pagination
  (`items[start:start+page_size]`), donc sur la liste déjà filtrée —
  cohérent avec "trier par année ramène le plus ancien de TOUTE la base
  filtrée", pas juste de la page affichée.
- Comparateurs : `title` (`str.lower`, `year` en clé secondaire pour les
  égalités de titre) ; `media_type` (`str`) ; `status` (`str`, `None`
  traité comme chaîne vide → toujours en premier en ordre croissant,
  cohérent avec le badge "non vérifié") ; `team` (`str`, `None` → chaîne
  vide) ; `quality` (`local_quality.resolution or 0`, tri numérique) ;
  `added_at` (`float`, `None` → `0.0`, donc en fin de liste en ordre
  décroissant "plus récent d'abord").
- Nouvelle fonction dédiée `_sort_library_items(items, sort, order)` dans
  `nfogen/gapscan_library.py` (colocalisée avec `LibraryItem`, testable
  isolément) plutôt qu'inline dans l'endpoint.

**Frontend** (`frontend/src/pages/LibraryPage.tsx`) :

- Ajout de la dépendance `@tanstack/react-table` (`npm install
  @tanstack/react-table`).
- Nouvel état `sort: { column: string; order: "asc" | "desc" } | null`,
  transmis à `libraryResults()` (nouveau paramètre `sort`/`order` dans
  `frontend/src/api/client.ts`, symétrique des paramètres backend) et
  inclus dans les dépendances du `useEffect` qui appelle `load()` (comme
  `page`/les filtres actuels) — change de tri renvoie automatiquement à
  la page 1 (`resetPageAnd`, pattern déjà utilisé pour les filtres).
- Le `<table>` HTML actuel devient piloté par
  `useReactTable({ columns, data: items, state: { sorting }, onSortingChange,
  getCoreRowModel: getCoreRowModel(), manualSorting: true })` — `manualSorting:
  true` car le tri est fait côté serveur (TanStack Table gère alors
  uniquement l'état visuel de l'en-tête cliqué + l'icône ↑/↓, pas le
  tri des données lui-même). Les colonnes NON triables aujourd'hui
  (case à cocher, Genres, actions) restent des colonnes TanStack avec
  `enableSorting: false`.
- Nouvelle colonne **"Ajouté le"** (`item.added_at`, formaté en date
  relative type "il y a 3 jours") — actuellement une donnée connue
  (`LibraryItem.added_at`, déjà utilisée par le filtre
  `added_since_days`) mais jamais affichée ; devient triable, utile pour
  repérer les ajouts récents sans dépendre du filtre.

## C. Pagination améliorée

- Bouton "⏮ Première page" ajouté à côté de "Précédent" (`setPage(1)`,
  `disabled={page <= 1}` comme "Précédent").
- La barre de pagination (Première page/Précédent/compteur/Suivant) est
  dupliquée **au-dessus** du tableau, en plus de sa position actuelle
  en dessous — évite de redescendre tout en bas d'une page de 50 lignes
  juste pour changer de page. Un seul composant `<PaginationBar />`
  extrait (évite la duplication de JSX), rendu deux fois avec les mêmes
  props.

## D. Suivi "En cours de seed" en direct

`frontend/src/pages/SeedQueuePage.tsx` : `loadSeedStatus()` passe d'un
appel unique au montage à un polling toutes les 4 secondes tant que la
page reste affichée (`setInterval` + nettoyage au démontage via le
`useEffect`, même patron que `pollSeedMatchUntilTerminal` dans
`LibraryPage.tsx`). Le premier chargement reste immédiat (pas d'attente
de 4s pour le premier affichage). Aucune modification backend — l'endpoint
`GET /gapscan/seed-status` existe déjà et est bon marché (proxy direct
vers qBittorrent).

## E. Réglages en grille 2 colonnes

`SettingsPage.tsx` : le conteneur racine passe de
`<div className="max-w-lg space-y-6">` à une grille responsive
(`<div className="grid grid-cols-1 gap-6 lg:grid-cols-2">`, un seul
colonne sur petit écran/mobile) :

- **Colonne gauche** : "Réglages de connexion" (URL de base) +
  "Authentification" (login/logout, section déjà existante).
- **Colonne droite** : "Comptes administrateurs" + "Configuration
  globale" (Sonarr/Radarr/qBittorrent/TMDB, déjà repliable — reste
  repliée par défaut, inchangé).

Chaque section garde son propre `max-w-lg` interne sur ses champs de
formulaire (`<input>`) pour rester lisible même dans une colonne large —
seul le conteneur RACINE perd sa contrainte globale.

## Hors périmètre (explicitement)

- Aucun changement du comportement des filtres existants (recherche,
  media_type, genre, statut, etc.) — uniquement l'ajout du tri, qui les
  complète.
- Aucune virtualisation de longue liste (react-window etc.) — YAGNI tant
  que `PAGE_SIZE = 50` reste la norme ; sujet séparable si jamais
  augmenté significativement plus tard.
- `ActiveTransfersTray` (bandeau global des transferts d'upload en cours)
  n'est PAS fusionné avec le suivi "En cours de seed" de
  `SeedQueuePage` — deux mécanismes distincts (upload direct vs. seed
  d'une release existante), pas de confusion fonctionnelle à lever ici.
- Pas de tri multi-colonnes (un seul critère de tri actif à la fois) —
  TanStack Table le permettrait nativement plus tard sans reprendre ce
  design si le besoin apparaît.
- Le tableau "En cours de seed" de `SeedQueuePage.tsx` (lecture seule du
  client de seed) ne passe PAS à TanStack Table dans ce lot — seul le
  tableau Bibliothèque est concerné par le tri (c'est lui qui est visé
  par le retour utilisateur "datatable"), `SeedQueuePage` ne fait que
  gagner le polling live (section D).
