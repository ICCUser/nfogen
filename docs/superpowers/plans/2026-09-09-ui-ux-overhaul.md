# Refonte UI/UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Contrainte projet explicite (memoire utilisateur) : jamais de subagents sur nfogen — executer chaque etape inline, dans cette meme session.**

**Goal:** Largeur pleine page partout, tableau Bibliothèque triable (TanStack Table, tri serveur sur toute la base), pagination plus pratique (retour page 1, barre dupliquée), suivi "En cours de seed" mis à jour en direct, page Réglages réorganisée en grille 2 colonnes.

**Architecture:** Le tri est calculé côté backend (`nfogen/gapscan_library.py`), sur la liste déjà filtrée et AVANT troncature de pagination, exposé via deux nouveaux paramètres de requête (`sort`, `order`) sur `GET /gapscan/library`. Côté frontend, `@tanstack/react-table` (headless) pilote uniquement l'état de tri et le rendu du `<thead>` — le `<tbody>` reste un `.map()` React classique sur `items` (une seule cellule `<td>` ajoutée, pour la nouvelle colonne "Ajouté le"), pour limiter la réécriture au strict nécessaire et garder le rendu de ligne existant (badges, boutons conditionnels) inchangé.

**Tech Stack:** FastAPI (backend), React + TypeScript + Tailwind (frontend), nouvelle dépendance npm `@tanstack/react-table`.

**Spec:** [docs/superpowers/specs/2026-09-09-ui-ux-overhaul-design.md](../specs/2026-09-09-ui-ux-overhaul-design.md)

## Global Constraints

- Le tri porte sur TOUTE la bibliothèque filtrée, pas seulement la page affichée (backend, pas client-side).
- `@tanstack/react-table` — headless, aucun style imposé, garde le Tailwind existant.
- Conteneur global : `max-w-7xl` → `max-w-[1600px]` dans `frontend/src/App.tsx`.
- `SettingsPage.tsx` : grille 2 colonnes (Connexion+Authentification à gauche, Comptes admin+Configuration globale à droite), perd son `max-w-lg` racine.
- Aucun changement des filtres existants, aucune virtualisation de liste, aucun tri multi-colonnes, `ActiveTransfersTray` non fusionné avec le suivi seed, le tableau de `SeedQueuePage.tsx` lui-même ne passe pas à TanStack Table (seule la Bibliothèque est concernée par le tri).
- Jamais de subagents sur ce projet (préférence utilisateur explicite, mémoire de session) — toute exécution reste inline.

---

### Task 1: Tri backend sur `GET /gapscan/library`

**Files:**
- Modify: `nfogen/gapscan_library.py` (ajoute `sort_library_items`)
- Modify: `nfogen/api.py:1064-1138` (endpoint `gapscan_library_endpoint`)
- Test: `tests/test_gapscan_library.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `nfogen.gapscan_library.sort_library_items(items: list[LibraryItem], sort: Optional[str], order: str) -> list[LibraryItem]` — colonnes reconnues : `"title"`, `"media_type"`, `"status"`, `"team"`, `"quality"`, `"added_at"` ; `sort` absent/inconnu → `items` renvoyé inchangé (même ordre) ; `order` : `"desc"` → décroissant, toute autre valeur (dont `"asc"`) → croissant.
- Consumes: `nfogen.gapscan_library.LibraryItem` (déjà défini, aucun changement de champ).

- [ ] **Step 1: Écrire les tests unitaires de `sort_library_items`**

Ajouter à la fin de `tests/test_gapscan_library.py` (le fichier importe déjà `GapResult`, `GapStatus`, `ReleaseQuality`, `RadarrMovieFile` — réutiliser les mêmes fixtures que le reste du fichier) :

```python
def _library_item(**overrides) -> LibraryItem:
    base = dict(
        media_type="movie", title="Matrix", year=1999, season_number=None,
        imdb_id="tt1", tvdb_id=None, tmdb_id="1", genres=[], added_at=None,
        local_quality=ReleaseQuality(raw=""), radarr_movie_id=1, sonarr_series_id=None,
        already_processed=False, last_processed_at=None, key="k1",
    )
    base.update(overrides)
    return LibraryItem(**base)


def test_sort_library_items_by_title_ascending():
    b = _library_item(title="Beta", key="b")
    a = _library_item(title="Alpha", key="a")
    result = gapscan_library.sort_library_items([b, a], "title", "asc")
    assert [i.key for i in result] == ["a", "b"]


def test_sort_library_items_by_title_descending():
    a = _library_item(title="Alpha", key="a")
    b = _library_item(title="Beta", key="b")
    result = gapscan_library.sort_library_items([a, b], "title", "desc")
    assert [i.key for i in result] == ["b", "a"]


def test_sort_library_items_by_quality_uses_resolution():
    low = _library_item(key="low", local_quality=ReleaseQuality(raw="", resolution=1080))
    high = _library_item(key="high", local_quality=ReleaseQuality(raw="", resolution=2160))
    unknown = _library_item(key="unknown", local_quality=ReleaseQuality(raw="", resolution=None))
    result = gapscan_library.sort_library_items([high, low, unknown], "quality", "asc")
    assert [i.key for i in result] == ["unknown", "low", "high"]


def test_sort_library_items_by_added_at_none_first_ascending():
    known = _library_item(key="known", added_at=1_000_000.0)
    unknown = _library_item(key="unknown", added_at=None)
    result = gapscan_library.sort_library_items([known, unknown], "added_at", "asc")
    assert [i.key for i in result] == ["unknown", "known"]


def test_sort_library_items_unknown_sort_returns_items_unchanged():
    a = _library_item(key="a")
    b = _library_item(key="b")
    result = gapscan_library.sort_library_items([a, b], "bogus", "asc")
    assert result == [a, b]


def test_sort_library_items_none_sort_returns_items_unchanged():
    a = _library_item(key="a")
    b = _library_item(key="b")
    result = gapscan_library.sort_library_items([a, b], None, "asc")
    assert result == [a, b]
```

Vérifier en haut du fichier que `gapscan_library` (le module, pas seulement des symboles importés) est bien importé — sinon ajouter `from nfogen import gapscan_library` à côté des imports existants.

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan_library.py -k sort_library_items -v`
Expected: FAIL — `AttributeError: module 'nfogen.gapscan_library' has no attribute 'sort_library_items'`

- [ ] **Step 3: Implémenter `sort_library_items`**

Dans `nfogen/gapscan_library.py`, en haut du fichier, la ligne d'import `from typing import Optional` devient :

```python
from typing import Any, Callable, Optional
```

Ajouter la fonction juste après `find_result_by_key` (avant `_compute_seed_match`) :

```python
def sort_library_items(
    items: list[LibraryItem], sort: Optional[str], order: str,
) -> list[LibraryItem]:
    """Trie `items` (deja filtres par l'appelant) selon `sort` -- AVANT
    troncature de pagination, pour que le tri porte sur toute la liste
    filtree, pas seulement la page affichee (retour utilisateur,
    2026-09-09 : "j'avais en tete du dynamique [...] datatable"). `sort`
    absent ou non reconnu : ordre d'origine (list_library()) inchange,
    jamais une exception. `order` : `"desc"` -> decroissant, toute autre
    valeur (dont `"asc"`) -> croissant."""
    key_funcs: dict[str, Callable[[LibraryItem], Any]] = {
        "title": lambda i: (i.title.lower(), i.year or 0),
        "media_type": lambda i: i.media_type,
        "status": lambda i: i.status or "",
        "team": lambda i: i.team or "",
        "quality": lambda i: i.local_quality.resolution or 0,
        "added_at": lambda i: i.added_at or 0.0,
    }
    key_func = key_funcs.get(sort) if sort is not None else None
    if key_func is None:
        return items
    return sorted(items, key=key_func, reverse=(order == "desc"))
```

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gapscan_library.py -k sort_library_items -v`
Expected: 6 passed

- [ ] **Step 5: Écrire le test d'intégration de l'endpoint**

Ajouter à `tests/test_api.py`, juste après `test_gapscan_library_refetches_after_ttl_expires` (réutilise `_CountingFakeGapscanRadarr` déjà défini plus haut dans le fichier) :

```python
class _ThreeNamedMoviesFakeRadarr(_FakeGapscanRadarr):
    def list_movie_files(self):
        return [
            RadarrMovieFile(movie_id=1, title="Beta", year=1999, imdb_id="tt1", tmdb_id=1),
            RadarrMovieFile(movie_id=2, title="Alpha", year=1999, imdb_id="tt2", tmdb_id=2),
            RadarrMovieFile(movie_id=3, title="Gamma", year=1999, imdb_id="tt3", tmdb_id=3),
        ]


def test_gapscan_library_sort_by_title_ascending(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    monkeypatch.setattr(mod, "RadarrClient", _ThreeNamedMoviesFakeRadarr)
    client = TestClient(mod.app)

    body = client.get("/gapscan/library", params={"sort": "title", "order": "asc"}).json()

    assert [i["title"] for i in body["items"]] == ["Alpha", "Beta", "Gamma"]


def test_gapscan_library_sort_by_title_descending(reload_api, monkeypatch):
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    monkeypatch.setattr(mod, "RadarrClient", _ThreeNamedMoviesFakeRadarr)
    client = TestClient(mod.app)

    body = client.get("/gapscan/library", params={"sort": "title", "order": "desc"}).json()

    assert [i["title"] for i in body["items"]] == ["Gamma", "Beta", "Alpha"]


def test_gapscan_library_sort_applies_before_pagination(reload_api, monkeypatch):
    """Le tri doit porter sur toute la liste, PUIS etre pagine -- pas
    l'inverse (sinon page=2 ne serait pas trie par rapport a page=1)."""
    mod = reload_api(
        NFOGEN_API_TOKEN=None,
        NFOGEN_RADARR_URL="http://radarr.local", NFOGEN_RADARR_API_KEY="y",
    )
    monkeypatch.setattr(mod, "RadarrClient", _ThreeNamedMoviesFakeRadarr)
    client = TestClient(mod.app)

    body = client.get(
        "/gapscan/library", params={"sort": "title", "order": "asc", "page": 1, "page_size": 2},
    ).json()

    assert [i["title"] for i in body["items"]] == ["Alpha", "Beta"]
```

- [ ] **Step 6: Lancer les tests, vérifier l'échec**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k "sort_by_title or sort_applies" -v`
Expected: FAIL — les 3 tests renvoient l'ordre Radarr d'origine (Beta, Alpha, Gamma), pas trié.

- [ ] **Step 7: Câbler `sort`/`order` dans l'endpoint**

Dans `nfogen/api.py`, la signature de `gapscan_library_endpoint` (ligne ~1064) gagne deux paramètres, juste après `processed`  :

```python
    processed: Optional[bool] = Query(None),
    sort: Optional[str] = Query(None),
    order: str = Query("asc"),
    page: int = Query(1, ge=1),
```

Et juste avant `total = len(items)` (actuellement ligne ~1132), insérer :

```python
    items = gapscan_library.sort_library_items(items, sort, order)

    total = len(items)
```

- [ ] **Step 8: Lancer les tests, vérifier le succès**

Run: `.venv/Scripts/python.exe -m pytest tests/test_api.py -k "library" -v`
Expected: tous PASS (les nouveaux + les existants, aucune régression sur les filtres déjà en place)

- [ ] **Step 9: Lint + suite complète**

Run: `.venv/Scripts/python.exe -m ruff check nfogen/gapscan_library.py nfogen/api.py tests/test_gapscan_library.py tests/test_api.py`
Expected: All checks passed!

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: tous PASS, aucune régression

- [ ] **Step 10: Commit**

```bash
git add nfogen/gapscan_library.py nfogen/api.py tests/test_gapscan_library.py tests/test_api.py
git commit -m "feat: tri serveur sur GET /gapscan/library (sort, order)

Nouveaux parametres de requete sort/order (title, media_type, status,
team, quality, added_at) -- s'applique sur la liste deja filtree, AVANT
troncature de pagination (spec docs/superpowers/specs/2026-09-09-ui-ux-overhaul-design.md,
section B), pour que le tri porte sur toute la bibliotheque filtree, pas
seulement la page affichee.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Largeur pleine page + grille Réglages

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`
- Test: `frontend/src/pages/SettingsPage.test.tsx`

**Interfaces:**
- Consumes: rien de nouveau (CSS/layout uniquement, aucune API touchée).
- Produces: rien consommé par d'autres tâches de ce plan (tâche indépendante des autres).

- [ ] **Step 1: Élargir le conteneur global**

Dans `frontend/src/App.tsx`, remplacer les deux occurrences de `max-w-7xl` :

```tsx
        <div className="mx-auto flex max-w-[1600px] items-center justify-between gap-3 px-4 py-3">
```

et

```tsx
      <main className="mx-auto max-w-[1600px] px-4 py-6">
```

- [ ] **Step 2: Écrire le test de la grille Réglages**

Lire d'abord `frontend/src/pages/SettingsPage.test.tsx` pour reprendre son pattern de rendu exact (mock de `../api/client`, wrapper `MemoryRouter`/`ProfileProvider` si utilisés). Ajouter :

```tsx
it("organise les sections en grille 2 colonnes, sans conteneur max-w-lg racine", async () => {
  renderPage();
  await screen.findByText("Réglages de connexion");

  const root = screen.getByText("Réglages de connexion").closest("div.grid");
  expect(root).not.toBeNull();
  expect(root?.className).not.toContain("max-w-lg");
});
```

(Adapter le nom de la fonction de rendu — `renderPage()` ou équivalent déjà présent dans le fichier — à ce qui existe réellement dans `SettingsPage.test.tsx`.)

- [ ] **Step 3: Lancer le test, vérifier l'échec**

Run: `cd frontend && npx vitest run SettingsPage.test.tsx -t "grille 2 colonnes"`
Expected: FAIL — le conteneur racine est toujours `<div className="max-w-lg space-y-6">`, pas de classe `grid`.

- [ ] **Step 4: Réorganiser `SettingsPage.tsx` en grille**

Le conteneur racine (actuellement `<div className="max-w-lg space-y-6">` à la ligne ~229, fermé par `</div>` à la toute fin du fichier ligne ~591) devient :

```tsx
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <div className="space-y-6">
        <div className="space-y-4">
          <h1 className="font-display text-xl font-semibold text-ink">Réglages de connexion</h1>
          {/* ... contenu existant de "Réglages de connexion" inchangé ... */}
        </div>

        <div className="space-y-3 border-t border-line pt-4">
          <h2 className="font-display text-lg font-semibold text-ink">Authentification</h2>
          {/* ... contenu existant de "Authentification" inchangé ... */}
        </div>
      </div>

      <div className="space-y-6">
        <div className="space-y-3 border-t border-line pt-4 lg:border-t-0 lg:pt-0">
          <h2 className="font-display text-lg font-semibold text-ink">Comptes administrateurs</h2>
          {/* ... contenu existant de "Comptes administrateurs" inchange ... */}
        </div>

        <div className="space-y-3 border-t border-line pt-4">
          {/* ... contenu existant de "Configuration globale" inchange ... */}
        </div>
      </div>
    </div>
```

Concrètement : ne RIEN changer à l'intérieur de chaque section (labels, inputs, handlers, logique conditionnelle `authRequired`/`authenticated`/etc. restent identiques) — seulement regrouper les 4 blocs existants (`Réglages de connexion`+`Authentification` d'un côté, `Comptes administrateurs`+`Configuration globale` de l'autre) dans deux `<div className="space-y-6">` côte à côte au lieu d'un seul `<div className="max-w-lg space-y-6">` empilé. Chaque section garde son propre style de champ (`<input className="... max-w-xs ...">` là où il existe déjà) — ne pas ajouter de `max-w` supplémentaire sur les sections elles-mêmes, seulement sur les `<input>` individuels s'ils n'en ont pas déjà (vérifier au fil de l'édition qu'aucun `<input>` ne s'étire sur toute la largeur de sa colonne sans nécessité).

- [ ] **Step 5: Lancer le test, vérifier le succès**

Run: `cd frontend && npx vitest run SettingsPage.test.tsx`
Expected: tous PASS (le nouveau + tous les existants, aucune régression sur les comportements de formulaire)

- [ ] **Step 6: Lint + build**

Run: `cd frontend && npm run lint && npm run build`
Expected: aucune erreur

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/pages/SettingsPage.tsx frontend/src/pages/SettingsPage.test.tsx
git commit -m "feat: largeur pleine page + Reglages en grille 2 colonnes

App.tsx : max-w-7xl -> max-w-[1600px] (toutes les pages en profitent).
SettingsPage.tsx : perd son max-w-lg racine qui l'etranglait en plus de
la contrainte globale, sections regroupees en grille 2 colonnes plutot
qu'empilees verticalement (retour utilisateur 2026-09-09 : 'la pleine
largeur n'est pas utilisee [...] c'est le foutoir').

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Tableau Bibliothèque triable (TanStack Table)

**Files:**
- Modify: `frontend/package.json` (nouvelle dépendance)
- Modify: `frontend/src/api/client.ts` (`libraryResults`)
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Test: `frontend/src/pages/LibraryPage.test.tsx`

**Interfaces:**
- Consumes: `nfogen/api.py` `GET /gapscan/library?sort=...&order=...` (Task 1).
- Produces: rien consommé par les tâches suivantes de ce plan (Task 4 modifie le même fichier juste après, dans une tâche séparée pour permettre une revue distincte).

- [ ] **Step 1: Installer la dépendance**

Run: `cd frontend && npm install @tanstack/react-table`
Expected: ajoute `@tanstack/react-table` à `frontend/package.json` (`dependencies`), version `^8.x` la plus récente au moment de l'installation.

- [ ] **Step 2: Étendre `libraryResults()` avec `sort`/`order`**

Dans `frontend/src/api/client.ts`, la signature de `libraryResults` (ligne ~348) :

```ts
export function libraryResults(
  opts: {
    q?: string;
    mediaType?: "movie" | "series";
    genre?: string;
    trackerGenre?: "anime" | "documentaire";
    status?: GapStatus | "not_verified";
    addedSinceDays?: number;
    processed?: boolean;
    sort?: string;
    order?: "asc" | "desc";
    page?: number;
    pageSize?: number;
    profile?: string;
  } = {},
): Promise<LibraryResultsPage> {
  const params = new URLSearchParams();
  if (opts.q) params.set("q", opts.q);
  if (opts.mediaType) params.set("media_type", opts.mediaType);
  if (opts.genre) params.set("genre", opts.genre);
  if (opts.trackerGenre) params.set("tracker_genre", opts.trackerGenre);
  if (opts.status) params.set("status", opts.status);
  if (opts.addedSinceDays !== undefined) params.set("added_since_days", String(opts.addedSinceDays));
  if (opts.processed !== undefined) params.set("processed", String(opts.processed));
  if (opts.sort) params.set("sort", opts.sort);
  if (opts.order) params.set("order", opts.order);
  params.set("page", String(opts.page ?? 1));
  params.set("page_size", String(opts.pageSize ?? 50));
  if (opts.profile) params.set("profile", opts.profile);
  return request<LibraryResultsPage>(`/gapscan/library?${params.toString()}`);
}
```

- [ ] **Step 3: Écrire le test de tri (échoue avant l'implémentation)**

Ajouter à `frontend/src/pages/LibraryPage.test.tsx`, juste avant le `describe`/test de pagination existant (`"affiche la pagination et change de page au clic sur Suivant"`) :

```tsx
it("trie par titre au clic sur l'en-tête, inverse l'ordre au second clic", async () => {
  const user = userEvent.setup();
  vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 1, season_packs: [] });

  renderPage();
  await waitFor(() => expect(libraryResults).toHaveBeenCalled());

  await user.click(screen.getByTestId("col-header-title"));
  await waitFor(() => {
    expect(vi.mocked(libraryResults)).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort: "title", order: "asc", page: 1 }),
    );
  });

  await user.click(screen.getByTestId("col-header-title"));
  await waitFor(() => {
    expect(vi.mocked(libraryResults)).toHaveBeenLastCalledWith(
      expect.objectContaining({ sort: "title", order: "desc", page: 1 }),
    );
  });
});
```

- [ ] **Step 4: Lancer le test, vérifier l'échec**

Run: `cd frontend && npx vitest run LibraryPage.test.tsx -t "trie par titre"`
Expected: FAIL — `screen.getByTestId("col-header-title")` introuvable (le `<thead>` actuel est du HTML statique).

- [ ] **Step 5: Ajouter l'état de tri et le câbler à `load()`**

Dans `frontend/src/pages/LibraryPage.tsx`, ajouter l'import en haut du fichier (à côté des imports React existants) :

```tsx
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
```

Après la déclaration `const [page, setPage] = useState(1);` (ligne ~112), ajouter :

```tsx
  const [sorting, setSorting] = useState<SortingState>([]);
```

Dans `load()` (ligne ~211), le premier argument passé à `libraryResults` gagne deux champs :

```tsx
  async function load() {
    try {
      const activeSort = sorting[0];
      const res = await libraryResults({
        q: debouncedQ || undefined,
        mediaType: mediaType || undefined,
        genre: genre || undefined,
        trackerGenre: trackerGenre || undefined,
        status: statusFilter || undefined,
        addedSinceDays: addedSinceDays ? Number(addedSinceDays) : undefined,
        processed: processed === "" ? undefined : processed === "true",
        sort: activeSort?.id,
        order: activeSort ? (activeSort.desc ? "desc" : "asc") : undefined,
        page,
        pageSize: PAGE_SIZE,
        profile,
      });
```

Le `useEffect` qui déclenche `load()` (ligne ~170) gagne `sorting` dans ses dépendances :

```tsx
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedQ, mediaType, genre, trackerGenre, statusFilter, addedSinceDays, processed, page, profile, sorting]);
```

Un changement de tri doit revenir à la page 1 (même logique que `resetPageAnd` pour les filtres) — remplacer l'`onSortingChange` de la table (ajoutée à l'étape suivante) par un wrapper :

```tsx
  function handleSortingChange(updater: SortingState | ((old: SortingState) => SortingState)) {
    setSorting((old) => {
      const next = typeof updater === "function" ? updater(old) : updater;
      setPage(1);
      return next;
    });
  }
```

- [ ] **Step 6: Définir les colonnes et l'instance TanStack Table**

Juste avant la fonction du composant `LibraryPage` (ou juste après les imports, comme `STATUS_BADGE_CLASS`), ajouter :

```tsx
const LIBRARY_COLUMNS: ColumnDef<LibraryItem>[] = [
  { id: "select", header: "", enableSorting: false },
  { id: "title", header: "Titre", accessorKey: "title" },
  { id: "media_type", header: "Type", accessorKey: "media_type" },
  { id: "genres", header: "Genres", enableSorting: false },
  { id: "status", header: "Statut", accessorKey: "status" },
  { id: "team", header: "Team", accessorKey: "team" },
  { id: "quality", header: "Ta version", accessorFn: (row) => row.local_quality.resolution ?? 0 },
  { id: "added_at", header: "Ajouté le", accessorKey: "added_at" },
  { id: "actions", header: "", enableSorting: false },
];
```

Nouvelle colonne "Ajouté le" (spec, section B : donnée déjà connue — `LibraryItem.added_at` — mais jamais affichée jusqu'ici, seulement utilisée par le filtre `added_since_days`). Ajouter aussi, à côté de `qualitySummary` (ligne ~55), le formateur de date relative réutilisé par le `<tbody>` (Step 7bis ci-dessous) :

```tsx
function formatAddedAt(addedAt: number | null): string {
  if (addedAt === null) return "—";
  const days = Math.floor((Date.now() / 1000 - addedAt) / 86400);
  if (days <= 0) return "aujourd'hui";
  if (days === 1) return "hier";
  if (days < 30) return `il y a ${days} j`;
  const months = Math.floor(days / 30);
  if (months < 12) return `il y a ${months} mois`;
  const years = Math.floor(months / 12);
  return `il y a ${years} an${years > 1 ? "s" : ""}`;
}
```

Dans le corps du composant, après la déclaration de `sorting`/avant le JSX retourné, créer l'instance de table :

```tsx
  const table = useReactTable({
    data: items ?? [],
    columns: LIBRARY_COLUMNS,
    state: { sorting },
    onSortingChange: handleSortingChange,
    manualSorting: true,
    enableMultiSort: false,
    getCoreRowModel: getCoreRowModel(),
  });
```

- [ ] **Step 7: Remplacer le `<thead>` statique par le rendu piloté par TanStack Table**

Remplacer (ligne ~761-772) :

```tsx
          <thead className="bg-surface-2 text-left text-ink-dim">
            <tr>
              <th className="px-4 py-2" />
              <th className="px-4 py-2">Titre</th>
              <th className="px-4 py-2">Type</th>
              <th className="px-4 py-2">Genres</th>
              <th className="px-4 py-2">Statut</th>
              <th className="px-4 py-2">Team</th>
              <th className="px-4 py-2">Ta version</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
```

par :

```tsx
          <thead className="bg-surface-2 text-left text-ink-dim">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    data-testid={`col-header-${header.column.id}`}
                    className={`px-4 py-2 ${header.column.getCanSort() ? "cursor-pointer select-none" : ""}`}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {header.column.getIsSorted() === "asc" && " ▲"}
                    {header.column.getIsSorted() === "desc" && " ▼"}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
```

Le `<tbody>` qui suit (ligne ~773 et après) continue de faire `.map(items)` directement, sans passer par `table.getRowModel()` — inchangé à une exception près, ajoutée à l'étape suivante : une cellule pour la nouvelle colonne "Ajouté le".

- [ ] **Step 8: Ajouter la cellule "Ajouté le" dans le `<tbody>`**

Dans la même ligne `<tr>` de `<tbody>`, insérer une nouvelle `<td>` juste après celle de "Ta version" (`{qualitySummary(item.local_quality)}`) et avant la `<td>` des actions ("Générer"/"Préparer l'upload"/etc.) :

```tsx
                <td className="whitespace-nowrap px-4 py-2 text-ink-dim">
                  {formatAddedAt(item.added_at)}
                </td>
```

- [ ] **Step 9: Lancer le test, vérifier le succès**

Run: `cd frontend && npx vitest run LibraryPage.test.tsx`
Expected: tous PASS (le nouveau test de tri + tous les tests existants, y compris pagination/filtres/seed-match)

- [ ] **Step 10: Lint + build**

Run: `cd frontend && npm run lint && npm run build`
Expected: aucune erreur (vérifier en particulier qu'`accessorFn`/`accessorKey` typent correctement contre `LibraryItem` — sinon ajuster les types `ColumnDef<LibraryItem>` selon les erreurs TypeScript réelles remontées par `tsc -b`)

- [ ] **Step 11: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/api/client.ts frontend/src/pages/LibraryPage.tsx frontend/src/pages/LibraryPage.test.tsx
git commit -m "feat: tableau Bibliotheque triable (TanStack Table, tri serveur)

@tanstack/react-table headless pilote uniquement l'etat de tri et le
rendu du <thead> -- le <tbody> reste un .map() React classique sur
items, aucun changement du rendu de ligne (badges, boutons conditionnels
seed-match/upload). Un clic sur un en-tete triable envoie sort/order au
backend (Task 1) et revient a la page 1.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Pagination améliorée (première page + barre dupliquée)

**Files:**
- Modify: `frontend/src/pages/LibraryPage.tsx`
- Test: `frontend/src/pages/LibraryPage.test.tsx`

**Interfaces:**
- Consumes: `page`/`setPage`/`total`/`PAGE_SIZE` (déjà définis dans `LibraryPage.tsx`, aucun changement de leur type).
- Produces: rien consommé ailleurs.

- [ ] **Step 1: Mettre à jour le test de pagination existant**

Le test existant `"affiche la pagination et change de page au clic sur Suivant"` (fin de `LibraryPage.test.tsx`) utilise `screen.getByRole("button", { name: "Suivant" })`, qui va échouer une fois la barre dupliquée (deux boutons "Suivant" au lieu d'un). Remplacer son contenu par :

```tsx
  it("affiche la pagination et change de page au clic sur Suivant", async () => {
    const user = userEvent.setup();
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 120, season_packs: [] });

    renderPage();
    await waitFor(() => expect(screen.getAllByText(/Page 1 \/ 3/).length).toBeGreaterThan(0));

    await user.click(screen.getAllByRole("button", { name: "Suivant" })[0]);

    await waitFor(() => {
      expect(libraryResults).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
    });
  });

  it("revient directement a la premiere page au clic sur Première page", async () => {
    const user = userEvent.setup();
    vi.mocked(libraryResults).mockResolvedValue({ items: [MATRIX_ITEM], total: 120, season_packs: [] });

    renderPage();
    await waitFor(() => expect(screen.getAllByText(/Page 1 \/ 3/).length).toBeGreaterThan(0));
    await user.click(screen.getAllByRole("button", { name: "Suivant" })[0]);
    await waitFor(() => expect(screen.getAllByText(/Page 2 \/ 3/).length).toBeGreaterThan(0));

    await user.click(screen.getAllByRole("button", { name: "Première page" })[0]);

    await waitFor(() => {
      expect(libraryResults).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1 }));
    });
  });
```

- [ ] **Step 2: Lancer les tests, vérifier l'échec**

Run: `cd frontend && npx vitest run LibraryPage.test.tsx -t "pagination"`
Expected: FAIL — un seul bouton "Suivant" trouvé (pas encore dupliqué), aucun bouton "Première page".

- [ ] **Step 3: Extraire un composant `PaginationBar` et dupliquer la barre**

Dans `frontend/src/pages/LibraryPage.tsx`, ajouter juste avant la fonction du composant `LibraryPage` :

```tsx
function PaginationBar({
  page, total, pageSize, onFirst, onPrev, onNext,
}: {
  page: number; total: number; pageSize: number;
  onFirst: () => void; onPrev: () => void; onNext: () => void;
}) {
  if (total <= pageSize) return null;
  return (
    <div className="flex items-center justify-between text-sm text-ink-dim">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onFirst}
          disabled={page <= 1}
          className="rounded-md border border-line-strong px-3 py-1.5 disabled:opacity-50"
        >
          Première page
        </button>
        <button
          type="button"
          onClick={onPrev}
          disabled={page <= 1}
          className="rounded-md border border-line-strong px-3 py-1.5 disabled:opacity-50"
        >
          Précédent
        </button>
      </div>
      <span>
        Page {page} / {Math.max(1, Math.ceil(total / pageSize))} — {total} résultats
      </span>
      <button
        type="button"
        onClick={onNext}
        disabled={page * pageSize >= total}
        className="rounded-md border border-line-strong px-3 py-1.5 disabled:opacity-50"
      >
        Suivant
      </button>
    </div>
  );
}
```

Remplacer le bloc de pagination existant (ligne ~890-909, sous le tableau) par un rendu de `<PaginationBar />`, et en ajouter un second juste au-dessus du `<table>` (avant la ligne `{items !== null && items.length > 0 && (` qui ouvre le tableau). Extrait ci-dessous **illustratif** (montre où s'insèrent les deux `<PaginationBar />` autour du bloc `<table>` déjà existant) — ne PAS remplacer le contenu réel du `<table>` (thead issu de `table.getHeaderGroups()`, tbody avec sa cellule "Ajouté le", tous deux mis en place aux Steps 7-8) par le commentaire ci-dessous, qui ne sert qu'à indiquer "le `<table>` existant reste ici, à sa place" :

```tsx
      {items !== null && items.length > 0 && (
        <PaginationBar
          page={page} total={total} pageSize={PAGE_SIZE}
          onFirst={() => setPage(1)}
          onPrev={() => setPage((p) => Math.max(1, p - 1))}
          onNext={() => setPage((p) => p + 1)}
        />
      )}

      {items !== null && items.length > 0 && (
        <table className="w-full overflow-hidden rounded-md border border-line bg-surface text-sm">
          {/* thead (table.getHeaderGroups()) + tbody : contenu deja en place, voir Task 3 */}
        </table>
      )}

      {items !== null && items.length > 0 && (
        <PaginationBar
          page={page} total={total} pageSize={PAGE_SIZE}
          onFirst={() => setPage(1)}
          onPrev={() => setPage((p) => Math.max(1, p - 1))}
          onNext={() => setPage((p) => p + 1)}
        />
      )}
```

(Supprimer l'ancien bloc `{total > PAGE_SIZE && (<div className="flex items-center justify-between ...">...</div>)}` qui existait avant — remplacé par les deux `<PaginationBar />` ci-dessus, qui gèrent déjà leur propre condition d'affichage via `total <= pageSize`.)

- [ ] **Step 4: Lancer les tests, vérifier le succès**

Run: `cd frontend && npx vitest run LibraryPage.test.tsx`
Expected: tous PASS

- [ ] **Step 5: Lint + build**

Run: `cd frontend && npm run lint && npm run build`
Expected: aucune erreur

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/LibraryPage.tsx frontend/src/pages/LibraryPage.test.tsx
git commit -m "feat: pagination Bibliotheque amelioree (premiere page + barre dupliquee)

PaginationBar extrait en composant, rendu au-dessus ET en dessous du
tableau -- evite de redescendre tout en bas d'une page de 50 lignes pour
changer de page (retour utilisateur 2026-09-09). Bouton 'Premiere page'
ajoute a cote de Precedent/Suivant.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Suivi "En cours de seed" en direct

**Files:**
- Modify: `frontend/src/pages/SeedQueuePage.tsx`
- Test: `frontend/src/pages/SeedQueuePage.test.tsx`

**Interfaces:**
- Consumes: `seedStatus()` (déjà définie dans `frontend/src/api/client.ts`, aucun changement de signature).
- Produces: rien consommé ailleurs (tâche indépendante des 4 précédentes).

- [ ] **Step 1: Lire le fichier de test existant**

Lire `frontend/src/pages/SeedQueuePage.test.tsx` en entier pour reprendre exactement son pattern de mock/rendu (nom de la fonction de rendu, mocks déjà en place pour `seedStatus`/`seedQueue`).

- [ ] **Step 2: Écrire le test de polling**

Ajouter (adapter le nom de la fonction de rendu à celui réellement utilisé dans le fichier) :

```tsx
it("rafraîchit l'état du seed automatiquement sans recharger la page", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.mocked(seedQueue).mockResolvedValue([]);
  vi.mocked(seedStatus)
    .mockResolvedValueOnce([
      { name: "a.mkv", size: 1000, progress: 0.1, ratio: 0, state: "downloading", upspeed: 100 },
    ])
    .mockResolvedValueOnce([
      { name: "a.mkv", size: 1000, progress: 0.5, ratio: 0, state: "downloading", upspeed: 500 },
    ]);

  renderPage();
  await screen.findByText("10%");

  await vi.advanceTimersByTimeAsync(4000);

  await screen.findByText("50%");
  expect(seedStatus).toHaveBeenCalledTimes(2);

  vi.useRealTimers();
});
```

- [ ] **Step 3: Lancer le test, vérifier l'échec**

Run: `cd frontend && npx vitest run SeedQueuePage.test.tsx -t "rafraîchit l'état"`
Expected: FAIL — `seedStatus` n'est appelé qu'une fois (`toHaveBeenCalledTimes(2)` échoue), "50%" jamais affiché.

- [ ] **Step 4: Ajouter le polling**

Dans `frontend/src/pages/SeedQueuePage.tsx`, remplacer :

```tsx
  useEffect(() => {
    load();
    loadSeedStatus();
  }, []);
```

par :

```tsx
  useEffect(() => {
    load();
    loadSeedStatus();
    // Suivi live (retour utilisateur 2026-09-09 : "il faut rafraichir la
    // page pour avoir un apercus [...] avoir en live la colonne envoi") --
    // rafraichit uniquement le statut du client de seed, pas la file
    // d'attente (load()), qui ne change que sur action utilisateur.
    const interval = window.setInterval(loadSeedStatus, 4000);
    return () => window.clearInterval(interval);
  }, []);
```

- [ ] **Step 5: Lancer le test, vérifier le succès**

Run: `cd frontend && npx vitest run SeedQueuePage.test.tsx`
Expected: tous PASS

- [ ] **Step 6: Lint + build**

Run: `cd frontend && npm run lint && npm run build`
Expected: aucune erreur

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/SeedQueuePage.tsx frontend/src/pages/SeedQueuePage.test.tsx
git commit -m "feat: suivi 'En cours de seed' rafraichi automatiquement

loadSeedStatus() etait appele une seule fois au montage -- retour
utilisateur 2026-09-09 : 'il faut rafraichir la page pour avoir un
apercus [...] le plus interessant est d'avoir en live la colonne envoi'.
Polling toutes les 4s tant que la page reste affichee, nettoye au
demontage.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Vérification finale (après les 5 tâches)

- [ ] `.venv/Scripts/python.exe -m pytest -q` → tous PASS
- [ ] `.venv/Scripts/python.exe -m ruff check nfogen/ tests/` → All checks passed!
- [ ] `cd frontend && npm run lint` → aucune erreur
- [ ] `cd frontend && npm test -- --run` → tous PASS
- [ ] `cd frontend && npm run build` → build réussi
- [ ] Relire `docs/superpowers/specs/2026-09-09-ui-ux-overhaul-design.md` section par section, confirmer chaque section (A-E) couverte par une tâche de ce plan.
