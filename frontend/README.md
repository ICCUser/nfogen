# nfogen — interface web

Interface React (Vite + TypeScript + Tailwind) pour nfogen, en complément
de la bibliothèque Python et de l'API appelée en script : deux usages.

1. **Générer** (page d'accueil) — envoyer un ou plusieurs fichiers (vidéo
   seule, ou album audio) et générer le NFO directement depuis le
   navigateur, avec métadonnées complémentaires en JSON. Le `release_name`
   est pré-rempli automatiquement à la sélection des fichiers
   (`POST /propose-name`, noms de fichiers seuls — aucun upload), pour les
   profils qui le configurent (voir
   [README principal](../README.md#proposition-automatique-de-release_name)).
   **Pour la vidéo**, l'analyse MediaInfo se fait **entièrement dans le
   navigateur** (WebAssembly, `mediainfo.js` — voir
   [README principal](../README.md#génération-vidéo-côté-navigateur-sans-upload)) :
   seules quelques Ko de texte partent au serveur (`POST /generate/json`),
   jamais les fichiers source. Repli automatique sur l'upload classique
   (`POST /generate`, multipart) si l'extraction locale échoue, ou pour les
   autres catégories (audio/jeux/ebook/3D).
2. **Profils** — gérer les **profils utilisateur** de nfogen (créer/éditer/
   supprimer leurs règles et templates, prévisualiser un rendu, exporter/
   importer en `.zip`) sans toucher au code Python.

Par défaut, le profil livré avec le paquet (C411) apparaît en lecture seule
dans l'écran Profils — mais un profil utilisateur du même nom le surcharge
(voir [le README principal](../README.md#gérer-des-profils-utilisateur-sans-toucher-au-code)).

## Lancer en développement

```bash
npm install
npm run dev          # http://localhost:5173
```

Le dev server proxy automatiquement `/api/*` vers `http://localhost:8000`
(voir `vite.config.ts`) : démarrez l'API nfogen séparément avant de l'utiliser.

```bash
# Dans nfo-tool/ (pas frontend/)
export NFOGEN_API_TOKEN=change-moi
export NFOGEN_PROFILES_DIR=/chemin/profils
uvicorn nfogen.api:app --port 8000
```

Renseignez le même token dans l'écran **Réglages** de l'interface (stocké en
`localStorage`, jamais envoyé ailleurs qu'à l'API configurée).

## Build de production

```bash
npm run build        # -> dist/
npm run preview      # sert le build localement
```

En production, `/api` ne pointe plus nulle part par défaut : configurez
l'URL réelle de l'API nfogen dans l'écran Réglages, ou servez `dist/`
derrière un reverse-proxy qui mappe `/api` vers l'API (même approche qu'en
dev, mais côté serveur web plutôt que Vite).

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
