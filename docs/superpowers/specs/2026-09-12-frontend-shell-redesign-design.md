# Refonte de la coquille UI/UX du frontend — Design

## Contexte et problème

Retour utilisateur (2026-09-12, session de brainstorming avec compagnon
visuel) : le frontend actuel (React + TypeScript + Vite + Tailwind, 6 pages
sous une simple nav du haut) souffre de deux problèmes distincts, tous deux
confirmés visuellement pendant la session :

1. **Panneaux/bannières mal placés** : le bandeau "Packs disponibles"
   casse le visuel au milieu de la page Bibliothèque, le champ de
   recherche flotte au milieu sans structure réelle, le panneau "Préparer
   l'upload" est un overlay centré, le bloc connexion/compte de la page
   Réglages bascule de position (gauche quand déconnecté, droite une fois
   connecté) selon l'état, et la page "À mettre en seed" a un encadré
   devenu inutile qui pousse le tableau utile hors de l'écran visible
   (scroll obligatoire).
2. **Look daté / manque de dynamisme visuel** : la structure "nav du haut
   + une colonne" ne rend pas justice à l'usage quotidien de l'outil.

**Contrainte explicite** : garder strictement la charte de couleurs déjà
en place (`frontend/src/index.css`, variables CSS thème clair/sombre) —
le problème est l'agencement, pas la palette.

## Périmètre

Refonte de la **coquille** (structure de navigation + gabarit de page +
traitement des panneaux/bannières), appliquée de façon cohérente à
l'ensemble des pages existantes (Générer, Bibliothèque, Profils, Réglages,
À mettre en seed). Pas de nouvelle fonctionnalité métier, pas de
changement des endpoints API consommés — uniquement comment l'existant
est présenté. Réalisé en une seule refonte globale (décision explicite de
l'utilisateur, pas un découpage page par page).

## Décisions validées avec le compagnon visuel

1. **Structure de navigation** : rail latéral fixe, icône + libellé,
   inspiré de la suite *arr (Radarr/Sonarr) — validé explicitement contre
   deux autres options (barre d'outils sans sidebar ; titre+recherche
   empilés pleine largeur). Sur mobile (< 768px), le rail devient une
   barre de navigation en bas d'écran (icônes seules).
2. **Barre d'outils par page** : une seule ligne sous le titre de page,
   regroupant recherche + filtres + actions — jamais d'élément flottant
   au milieu du contenu. Sur mobile, la recherche passe sur sa propre
   ligne pleine largeur si la barre ne tient pas.
3. **Couleurs** : aucune nouvelle couleur — reprise exacte des variables
   CSS existantes (`--color-accent: #6bc9b3` en thème sombre / `#0f6a5e`
   en thème clair, etc.). L'accent reste réservé à l'action principale de
   chaque page et à l'item de navigation actif ; les actions secondaires
   restent neutres (bordure, pas de fond) pour ne pas diluer l'accent.
4. **Icônes** : bibliothèque Lucide (icônes ligne, cohérentes avec le
   style *arr) — remplace toute icône ad hoc/emoji existante dans la nav
   et les boutons.
5. **Bannières/alertes contextuelles** (ex: "packs disponibles") : ligne
   fine ancrée au-dessus du tableau concerné (jamais au milieu du
   contenu), une par élément détecté, avec son action directement dessus,
   disparaît une fois traitée — validé contre deux autres options
   (panneau latéral dédié ; notification flottante façon toast).
6. **Panneaux superposés** (ex: "Préparer l'upload") : passent d'un
   overlay centré (`UploadPrepPanel`, qui avait déjà eu un bug de hauteur
   non bornée cette session) à un **tiroir latéral droit** — cohérent
   avec le rail à gauche, jamais de superposition centrale qui casse la
   lecture du contenu en dessous.
7. **Corrections ponctuelles identifiées pendant le cadrage** :
   - `SeedQueuePage.tsx` : suppression de l'encadré devenu inutile en
     haut de page — le tableau utile remonte directement sous le titre,
     visible sans scroll.
   - `SettingsPage.tsx` : le bloc connexion/compte garde une position
     FIXE dans la grille de la page, qu'on soit connecté ou non — plus de
     bascule gauche/droite pilotée par l'état d'authentification.
8. **Responsive** : chaque décision ci-dessus vérifiée pour un usage
   confortable sur 16:9, 16:10, tablette et téléphone — pas seulement un
   écran de bureau large (retour utilisateur explicite sur ce point).

## Architecture et composants

**Nouveau composant `AppShell`** (remplace la structure actuelle de
`App.tsx:39-66`) : rail latéral (nav) + zone de contenu, plutôt que
l'actuel `<header>` pleine largeur + `<main>`. Le rail est un nouveau
composant `Sidebar.tsx` (liste de liens avec icône Lucide + libellé,
actif = accent + fond `surface-2`, repli en barre du bas sous 768px via
media query Tailwind).

**Nouveau composant `PageToolbar`** — remplace la disposition ad hoc
actuelle de chaque page (titre + `flex items-center justify-between` +
boutons épars, voir `LibraryPage.tsx:526-568` par exemple) par un
composant partagé : titre + zone d'actions (recherche/filtres/boutons),
avec le comportement responsive (recherche qui passe en pleine largeur en
dessous d'un seuil) implémenté UNE SEULE FOIS plutôt que dupliqué par
page.

**Nouveau composant `Drawer`** (tiroir latéral droit) — remplace le
patron d'overlay centré actuel utilisé par `UploadPrepPanel.tsx`. Même
principe d'API que l'overlay actuel (`onClose`, contenu en `children`)
pour limiter le changement dans les pages qui l'utilisent déjà.

**Nouveau composant `InlineBanner`** — la bannière fine pour les alertes
contextuelles (packs disponibles, etc.), consommé par `LibraryPage.tsx`
à la place du bloc actuel.

**Fichiers modifiés (structure, pas de logique métier)** : `App.tsx`,
`LibraryPage.tsx`, `SeedQueuePage.tsx`, `SettingsPage.tsx`,
`GeneratePage.tsx`, `ProfilesListPage.tsx`, `ProfileEditorPage.tsx`,
`UploadPrepPanel.tsx` (adapté pour rendre son contenu dans `Drawer`
plutôt que son overlay actuel).

**Nouvelle dépendance** : `lucide-react` (icônes).

## Ce qui NE change PAS

Aucun appel API, aucune logique métier, aucun test de comportement
fonctionnel existant ne doit changer de résultat — uniquement la
structure/le rendu. Les tests existants (`*.test.tsx`) qui vérifient du
texte/des données affichées doivent continuer à passer ; ceux qui
vérifient une structure DOM précise devenue obsolète (ex: position d'un
bouton dans l'ancien layout) seront mis à jour dans le plan
d'implémentation, page par page.

## Tests

Chaque nouveau composant partagé (`Sidebar`, `PageToolbar`, `Drawer`,
`InlineBanner`) reçoit ses propres tests (rendu, comportement responsive
via resize, gestion `onClose`/actions). Les tests de page existants sont
adaptés au fur et à mesure de leur migration vers les nouveaux
composants, jamais supprimés sans remplacement équivalent.
