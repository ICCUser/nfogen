# Audit front NFOGen — grille « Apple Design »

- **Date** : 2026-10-14
- **Périmètre** : `nfo-tool/frontend/src` (React 19, Tailwind 4, Vite), environ 4 500 lignes hors tests. Ont été lus : le shell (`App`, `Sidebar`), les composants partagés, `GeneratePage`, `LibraryPage` et `UploadPrepPanel` en entier, ainsi que les parties clés de `ProfileEditorPage`, `ProfilesListPage`, `SeedQueuePage` et `SettingsPage`.
- **Référentiel** : skill `apple-design` (emilkowalski/skills), installé dans `NFOGen/.agents/skills/apple-design`.
- **Vérification visuelle** : le serveur Vite a été lancé seul, sans l'API, et la Bibliothèque a été affichée en 375 px. Les tableaux remplis n'ont donc pas pu être affichés. Les constats qui les concernent viennent de la lecture du code et sont indiqués « (code) ».

Légende : **P1** à corriger en priorité · **P2** gêne réelle · **P3** finition.

---

## Points forts (à conserver)

- **Thème par tokens et mode sombre automatique** (`index.css`) : mêmes noms de variables dans les deux thèmes, aucun préfixe `dark:` dans le JSX. C'est une base saine (§16 Craft, « couleurs qui s'adaptent »).
- **Toutes les tâches longues tournent en arrière-plan et sont annulables** : aperçu, commit, intégrité, seed-match. Cela répond bien au principe *Agency* et au « ne jamais bloquer l'entrée » (§3).
- **La confirmation de l'upload direct** est le bon usage d'une confirmation : action réellement irréversible et publique (§16 Agency).
- **Le tiroir arrive à droite, à l'opposé du rail.** Les panneaux d'action ont désormais une origine spatiale stable (§7).
- **Libellés de navigation spécifiques** (« Bibliothèque », « À mettre en seed ») plutôt que génériques (§16 « Direct, specific labels »).
- **`ErrorBoundary` avec `key={pathname}`** : l'utilisateur n'est jamais piégé sur une page cassée (§16 Wayfinding).
- **Le debounce de 400 ms sur la recherche** est justifié (coût Sonarr côté serveur). Ce n'est pas une latence gratuite, et la valeur saisie reste immédiate.

---

## P1 — À corriger en priorité

### 1. Tableaux sans défilement horizontal : toute la page déborde sur mobile (code)
`LibraryPage.tsx:926` et `ProfilesListPage.tsx:114` rendent `<table className="w-full overflow-hidden …">` sans conteneur. La Bibliothèque a 10 colonnes, plusieurs en `whitespace-nowrap` (statut, actions avec 2 à 3 liens). En dessous de 768 px, le tableau élargit donc toute la page. `SeedQueuePage.tsx:179` fait déjà ce qu'il faut (`<div className="overflow-x-auto …">`).
**Correctif** : envelopper chaque tableau dans `overflow-x-auto rounded-md border` et retirer `overflow-hidden` du `<table>`. Sur mobile, envisager à terme une vue en cartes pour la Bibliothèque (§16 Flexibility).

### 2. Aucun retour visuel à l'appui, aucun focus stylé
Aucune occurrence de `active:` ni de `focus` ou `focus-visible` dans le code. Les boutons n'ont que `hover:opacity-90`, et le survol n'existe pas au tactile. Le focus clavier dépend des réglages par défaut du navigateur, ce qui est incohérent entre `select`, `button` et `a`.
**Correctif** (§1 Response) : définir une fois des classes de base de bouton, par exemple dans `@layer components`, avec
`active:scale-[0.97] transition-transform duration-100 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`.
Il y a aujourd'hui plus de 40 boutons, chacun avec ses classes copiées-collées. Un composant `<Button variant="primary|secondary|link">` réglerait le problème d'un coup et supprimerait la dérive des tailles (`px-3 py-1.5 text-xs`, `px-4 py-2 text-sm`, etc.).

### 3. Le tiroir (`Drawer.tsx`) n'est ni animé ni accessible
- **Apparition et disparition sèches** : le tiroir « téléporte ». Il devrait glisser depuis la droite et repartir vers la droite (§7, chemin symétrique), le voile passant de 0 à 50 % d'opacité.
  - En CSS pur : `transform: translateX(100%)` vers `0` avec un easing critique (≈ `cubic-bezier(.32,.72,0,1)`, 300 ms), un état de sortie et le démontage à la fin de la transition.
  - Avec `motion` : `spring`, `bounce: 0`, `duration: 0.35`, ce qui donne une animation interruptible si l'on rouvre pendant la fermeture (§3, §4).
- **Accessibilité** : `role="dialog"` est posé sur un enfant (`UploadPrepPanel.tsx:359`) et non sur le panneau. Le focus n'est pas déplacé à l'ouverture ni rendu au déclencheur à la fermeture. Il n'y a pas de piège de focus ni de verrouillage du défilement de la page. Échap est géré par `UploadPrepPanel`, pas par `Drawer`, donc tout futur tiroir devra le réimplémenter.
- **Option simple** : `<dialog>` natif + `showModal()` fournit gratuitement le focus, Échap, l'inertie de l'arrière-plan et `::backdrop`.
- **`prefers-reduced-motion`** : remplacer le glissement par un fondu de 200 ms (§14).

### 4. Boîtes `confirm()` natives, dont une pour une action non destructive
Il y en a 4 : `UploadPrepPanel.tsx:266` et `:292`, `ProfileEditorPage.tsx:73`, `SettingsPage.tsx:208`. Celle de la **fermeture du tiroir** (`:266`) précise elle-même que « rien n'est perdu côté serveur ». Selon le principe *Agency*, une confirmation sert à un acte destructif et irréversible. En abuser habitue à cliquer sans lire, ce qui affaiblit justement la confirmation utile de l'upload direct.
**Correctif** :
- Supprimer la confirmation de fermeture.
- La remplacer par un indicateur persistant, par exemple une pastille « 1 groupe prêt, non envoyé » sur la ligne ou dans `ActiveTransfersTray`, qui permet de rouvrir le panneau.
- Garder une confirmation pour l'upload direct et les suppressions, mais intégrée à l'interface : bouton qui passe en « Confirmer l'upload direct ? » sur place, ou petite modale stylée. `confirm()` bloque le thread, ignore le thème sombre et affiche « localhost:8000 indique… ».

### 5. Statuts asynchrones invisibles pour les lecteurs d'écran et retour éphémère
Il n'y a aucun `aria-live` ni `role="status"` ou `role="alert"`. La progression du scan, « Enregistré. », les erreurs d'envoi et les résultats de seed apparaissent sans être annoncés. Par ailleurs, « Enregistré. » disparaît après 2 s (`LibraryPage.tsx:483`, `SettingsPage.tsx:89` et `:147`).
**Correctif** : mettre `role="status"` sur les zones de progression et de succès, et `role="alert"` sur les bandeaux d'erreur. Remplacer le texte temporaire par un état stable sur le bouton lui-même (« Enregistré ✓ » jusqu'à la prochaine modification). C'est le retour de type *completion* (§16).

### 6. `index.html` : `lang="en"` et `<title>frontend</title>`
Toute l'interface est en français. Un lecteur d'écran lira donc le français avec une voix anglaise. L'onglet du navigateur affiche « frontend ».
**Correctif** : `lang="fr"`, `<title>nfogen</title>`, éventuellement suivi du nom de la page via un petit `useEffect` par route (§16 Wayfinding : « où suis-je ? »).

---

## P2 — Gêne réelle

### 7. En-têtes triables inaccessibles au clavier
Trois tableaux utilisent `<th onClick>`, sans bouton, sans `tabIndex` et sans `aria-sort`. L'indicateur est du texte ` ▲`/` ▼` collé au libellé.
**Correctif** : `<th aria-sort="ascending|descending|none"><button className="inline-flex items-center gap-1">Titre <ChevronUp/Down size={12}/></button></th>`.

### 8. Deux styles d'onglets pour la même idée (`ProfileEditorPage.tsx:195-225`)
Les catégories sont des onglets soulignés, les sections (Règles, Template, Aperçu) des pilules pleines. Aucune n'a `role="tablist"`, `role="tab"` ni `aria-selected`. Selon *Familiarity*, ce qui se ressemble doit se comporter pareil, et inversement. Ici, deux niveaux hiérarchiques utilisent deux langages visuels sans relation claire.
**Correctif** : garder le soulignement pour le niveau 1 (catégorie) et prendre un contrôle segmenté pour le niveau 2. Ajouter les rôles ARIA et la navigation aux flèches.

### 9. Bibliothèque : tout est au même niveau (*Simplicity, not minimalism*)
De haut en bas, l'écran empile :
- la barre d'outils (4 contrôles) ;
- un paragraphe d'aide ;
- le panneau de transferts ;
- deux bandeaux d'avertissement ;
- la configuration du profil ;
- un bandeau d'erreur ;
- la progression ;
- le journal ;
- **7 filtres + 3 boutons de sélection** ;
- les packs ;
- la pagination ;
- le tableau.

Constat sur mobile (capture en 375 px) : le premier filtre commence à mi-écran et le tableau n'est même pas visible. Par ailleurs :
- deux boutons primaires de couleur accent coexistent : « Lancer un scan complet » et « Vérifier sur le tracker (0 sélectionnés) » ;
- les actions par ligne sont 2 à 4 liens soulignés côte à côte.

**Pistes** :
- Rendre visibles par défaut seulement Recherche, Type et Statut. Les 4 autres filtres passent derrière un bouton « Filtres (n) » qui indique le nombre de filtres actifs.
- Rendre la barre de sélection contextuelle : elle n'apparaît, collante en bas, que quand au moins une ligne est cochée (« 3 sélectionnés · Vérifier · Désélectionner »). C'est le modèle de sélection de Photos et Mail.
- Déplacer la configuration du profil vers Réglages ou Profils. Elle n'est utile qu'une fois, et un bandeau qui renvoie vers elle suffit tant qu'elle n'est pas configurée.
- Regrouper les actions de ligne dans un menu `…`, en gardant l'action principale visible.

### 10. Mobile : barre du bas et en-tête
- La barre du bas ne tient pas compte de l'encoche ou de la barre d'accueil (`pb-[env(safe-area-inset-bottom)]`). Il faut aussi `viewport-fit=cover` dans la meta viewport.
- Le libellé « À mettre en seed » passe sur 2 lignes (observé), ce qui décale la grille d'icônes. Il faut un libellé court sur mobile (« Seed ») et le libellé complet sur le rail.
- Un en-tête pleine largeur ne sert qu'au sélecteur de profil. Sur mobile, il pourrait rejoindre la barre d'outils de page.
- L'icône `Home` sur « Générer » contredit le libellé spécifique. Une icône `FilePlus` ou `Wand` serait plus juste.

### 11. Grilles `grid-cols-2` fixes
Concernés : `GeneratePage.tsx:222`, `LibraryPage.tsx:622`, `SettingsPage.tsx:451`, et `CategoryRulesForm.tsx:40`, `:100`, `:224`. En 375 px, les champs URL et clé font environ 160 px. Dans `GeneratePage`, le select « Catégorie » occupe une demi-ligne vide sur desktop.
**Correctif** : `grid-cols-1 sm:grid-cols-2`.

### 12. Barres de progression : `transition-all` sur `width`, sans prise en compte de la réduction des mouvements
Fichiers : `ActiveTransfersTray.tsx:80`, `LibraryPage.tsx:692`, `UploadPrepPanel.tsx:459` et `:521`. Animer `width` relance la mise en page à chaque image. Le scan sans total affiche un « 10 % » figé au lieu d'un état indéterminé.
**Correctif** :
- `transform: scaleX(p)` avec `origin-left` et `transition-transform duration-[1400ms] ease-linear`. La durée est calée sur le polling de 1,5 s pour que la barre avance en continu au lieu de sauter (§11).
- Une barre indéterminée (balayage doux) quand `total === 0`.
- Dans tous les cas, `motion-reduce:transition-none` (§14).

### 13. Token inexistant
`LibraryPage.tsx:538` : `hover:bg-surface-hover`. Ce token n'est pas défini dans `@theme`, donc le bouton « Rafraîchir » n'a aucun état de survol. Utiliser `hover:bg-surface-2` comme ailleurs.

---

## P3 — Finition (*Craft*)

### 14. Emojis et caractères à la place d'icônes
On compte 17 occurrences (`✅ ⚠ ▲ ▼`) alors que `lucide-react` est déjà présent. Le rendu des emojis varie selon l'OS, ne suit pas la couleur sémantique et reste coloré en mode sombre. Le dépliant « Configuration du profil » (`LibraryPage.tsx:611`) utilise `▲/▼` sans `aria-expanded`, alors que le bandeau des packs juste en dessous a `ChevronDown` et `aria-expanded`. C'est le même contrôle, avec deux implémentations.
Ajouter aussi `transition-transform` sur la rotation du chevron.

### 15. Typographie
- **Polices** : trois familles Google Fonts sont chargées depuis un CDN. Pour un outil auto-hébergé sur NAS, cela crée une dépendance réseau externe, un flash de police de remplacement au chargement, et transmet votre IP à Google. L'identité typographique est assumée (`index.css`), il ne s'agit pas de la retirer. Il suffit de l'**auto-héberger** (`@fontsource/archivo`, `@fontsource/public-sans`, `@fontsource/ibm-plex-mono`), ou de passer à `system-ui` et `ui-monospace` comme le recommande §15.
- **Tracking** : les `h1` en Archivo `text-xl` n'ont pas de tracking négatif. Ajouter `tracking-tight` (≈ -0,02em) aux titres d'affichage et laisser le corps de texte à 0.
- **Taille minimale** : `text-[10px]` dans le journal du scan (`LibraryPage.tsx:717`) est sous le seuil de lisibilité, d'autant que les badges colorés réduisent le contraste. Passer à `text-[11px]` minimum, ou en `text-xs` avec un padding réduit.
- **Interlignage** : correct par défaut. Pour le tableau dense, `leading-tight` sur les cellules mono gagnerait de la hauteur.

### 16. Matériaux (optionnel)
Le rail et la barre du bas sont opaques. Pour un outil dense, c'est un choix défendable. Si l'on veut l'effet « couche flottante » (§12) sur mobile :
- barre du bas en `bg-surface/80 backdrop-blur-xl`, avec un liseré supérieur clair et le contenu qui défile dessous ;
- obligatoirement, la variante `@media (prefers-reduced-transparency: reduce)` en fond plein (§14).

Ce n'est pas prioritaire.

### 17. Interactions par geste
Aucune n'existe aujourd'hui (pas de glisser, de balayage ni de tiroir déplaçable). C'est normal pour ce type d'outil. Si le tiroir devient « glissable pour fermer » sur mobile, appliquer §2, §5, §6 et §9 du skill : Pointer Events avec capture, transmission de la vitesse, projection `d≈0.998` et effet élastique. Sinon, pas de travail à prévoir.

---

## Ordre de traitement suggéré

| # | Lot | Fichiers | Effort |
|---|-----|----------|--------|
| 1 | `overflow-x-auto` sur les tableaux, `grid-cols-1 sm:grid-cols-2`, token `surface-hover`, `lang`/`title` | LibraryPage, ProfilesListPage, GeneratePage, SettingsPage, CategoryRulesForm, index.html | XS |
| 2 | Composant `<Button>` avec `active:` et `focus-visible:` partout | nouveau `components/Button.tsx` + tous les écrans | M |
| 3 | `Drawer` sur `<dialog>` natif : animation d'entrée et de sortie, focus, Échap, réduction des mouvements | Drawer, UploadPrepPanel | S |
| 4 | Retrait du `confirm()` de fermeture, confirmations intégrées, `role="status"`/`"alert"`, retour « Enregistré » stable | UploadPrepPanel, ProfileEditorPage, SettingsPage, LibraryPage | S |
| 5 | En-têtes triables accessibles, onglets ARIA, icônes Lucide à la place des emojis | 3 tableaux, ProfileEditorPage | S |
| 6 | Bibliothèque : filtres repliables et barre de sélection contextuelle | LibraryPage | M |
| 7 | Barres de progression en `scaleX`, état indéterminé, `motion-reduce` | 3 composants | XS |
| 8 | Polices auto-hébergées, tracking des titres, taille minimale 11 px, safe-area et libellés mobiles | index.css, index.html, Sidebar | XS |

Tous les lots peuvent être testés avec les tests Vitest existants (`npm test`). Les lots 3 et 4 modifient des comportements couverts par `Drawer.test.tsx` et `UploadPrepPanel.test.tsx` (la fermeture avec confirmation) : il faudra mettre ces tests à jour, pas seulement les faire passer.
