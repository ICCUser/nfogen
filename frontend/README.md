# nfogen — interface web

Interface React (Vite + TypeScript + Tailwind) pour nfogen. Deux usages :

1. **Générer** (accueil) — envoyer des fichiers (vidéo, ou album audio) et
   générer le NFO depuis le navigateur, avec métadonnées JSON
   complémentaires. `release_name` pré-rempli via `POST /propose-name` (noms
   de fichiers seuls, aucun upload). Pour la vidéo, analyse MediaInfo
   entièrement dans le navigateur (WebAssembly, `mediainfo.js`) : seul le
   texte résultant part au serveur (`POST /generate/json`). Repli sur
   l'upload classique (`POST /generate`) si l'extraction locale échoue, ou
   pour les autres catégories. Voir [README principal](../README.md).
2. **Profils** — créer/éditer/supprimer profils utilisateur (règles +
   templates), prévisualiser, exporter/importer `.zip`, sans toucher au code.

C411 (livré avec le paquet) apparaît en lecture seule dans l'écran Profils ;
un profil utilisateur du même nom le surcharge.

## Lancer en développement

```bash
npm install
npm run dev          # http://localhost:5173
```

Le dev server proxy `/api/*` vers `http://localhost:8000` (`vite.config.ts`) :
démarrez l'API séparément.

```bash
# Dans nfo-tool/ (pas frontend/)
export NFOGEN_API_TOKEN=change-moi
export NFOGEN_PROFILES_DIR=/chemin/profils
uvicorn nfogen.api:app --port 8000
```

Connectez-vous avec ce token dans l'écran **Réglages** : `POST /login` pose
un cookie de session httpOnly, le token n'est jamais stocké côté navigateur
(seule l'URL de base de l'API est en `localStorage`).

## Build de production

```bash
npm run build        # -> dist/
npm run preview      # sert le build localement
```

En production, configurez l'URL de l'API dans l'écran Réglages, ou servez
`dist/` derrière un reverse-proxy qui mappe `/api` vers l'API.

## Tests

```bash
npm run test          # vitest, execute aussi en CI
```

Vitest + Testing Library (jsdom). Pas de mock du DOM local storage natif
(peu fiable selon la version de Node) : `src/setupTests.ts` fournit un
polyfill deterministe.

## Structure

- `src/api/` — client HTTP (`client.ts`), types miroir de `rules.schema.json`
  (`types.ts`), réglages de connexion persistés (`settings.ts`).
- `src/pages/GeneratePage.tsx` — accueil : upload de fichier(s) + métadonnées
  JSON → NFO, avec téléchargement (nom imposé par le profil). Vidéo : extraction
  locale via `src/lib/clientMediaInfo.ts`, sinon `generateUpload` (multipart).
- `src/lib/clientMediaInfo.ts` — extraction MediaInfo 100% navigateur
  (WebAssembly, `mediainfo.js`) : texte + métadonnées structurées (résolution,
  codec, langues), par plages d'octets (`Blob.slice()`), jamais le fichier
  entier en mémoire.
- `src/pages/ProfilesListPage.tsx` / `ProfileEditorPage.tsx` / `SettingsPage.tsx`
  — gestion des profils utilisateur et réglages de connexion.
- `src/components/rules/` — formulaire d'édition des règles d'une catégorie
  (tokens, croisements avec le fichier réel, vérifications de langue).
- `src/components/` — éditeur de template brut, panneau d'aperçu live
  (`POST /generate/json`, n'écrit rien sur disque), éditeurs de liste/clé-valeur
  génériques réutilisés par le formulaire de règles.
