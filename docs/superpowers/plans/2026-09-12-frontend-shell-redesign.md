# Refonte de la coquille UI/UX du frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer la nav du haut par un rail latéral fixe (façon Radarr/Sonarr), construire les 3 composants partagés (barre d'outils de page, tiroir latéral, bannière d'alerte) et migrer `LibraryPage` en premier consommateur complet, en gardant strictement la charte de couleurs existante.

**Architecture:** 4 nouveaux composants réutilisables (`Sidebar`, `PageToolbar`, `Drawer`, `InlineBanner`) construits et testés isolément, puis câblés dans `App.tsx` (coquille) et dans `LibraryPage.tsx` (premier consommateur complet — c'est la page qui cumule les 3 besoins : bannière de packs, barre d'outils recherche/filtres, panneau `UploadPrepPanel` à convertir en tiroir).

**Tech Stack:** React 19 + TypeScript + Vite + Tailwind CSS v4, nouvelle dépendance `lucide-react` (icônes).

**Spec:** [docs/superpowers/specs/2026-09-12-frontend-shell-redesign-design.md](../specs/2026-09-12-frontend-shell-redesign-design.md)

## Global Constraints

- Couleurs : uniquement les variables CSS déjà en place dans `frontend/src/index.css` (`--color-accent`, `--color-surface`, `--color-surface-2`, `--color-ink`, `--color-ink-dim`, `--color-line`, `--color-line-strong`) — aucune nouvelle couleur.
- Icônes : bibliothèque `lucide-react`, jamais d'emoji ni d'autre police d'icônes.
- Responsive : rail latéral -> barre du bas sous 768px (breakpoint Tailwind `md`).
- Aucun changement d'appel API ni de logique métier — uniquement la structure/le rendu.
- Périmètre de CE plan : composants partagés + coquille (`App.tsx`) + migration complète de `LibraryPage.tsx` uniquement. `SeedQueuePage.tsx`/`SettingsPage.tsx`/`GeneratePage.tsx`/`ProfilesListPage.tsx`/`ProfileEditorPage.tsx` héritent déjà du nouveau rail via `App.tsx` (Task 2) mais leur propre contenu interne (barre d'outils, bannières, encadré inutile de `SeedQueuePage`, position du bloc connexion de `SettingsPage`) est traité dans un plan de suivi séparé — spec trop large pour un seul plan (voir "Scope Check" de writing-plans), et `LibraryPage` sert de preuve de concept avant de généraliser.

---

## Task 1: `lucide-react` + composant `Sidebar`

**Files:**
- Modify: `frontend/package.json` (nouvelle dépendance)
- Create: `frontend/src/components/Sidebar.tsx`
- Test: `frontend/src/components/Sidebar.test.tsx`

**Interfaces:**
- Consumes: rien (composant autonome, utilise `NavLink`/`useLocation` de `react-router-dom`, déjà une dépendance).
- Produces: `export default function Sidebar(): JSX.Element` — pas de props, la liste des liens est câblée en dur dans le composant (5 entrées : Générer `/`, Bibliothèque `/library`, À mettre en seed `/seed-queue`, Profils `/profils`, Réglages `/settings`). Consommé par Task 2 (`App.tsx`).

- [ ] **Step 1: Installer lucide-react**

```bash
cd frontend && npm install lucide-react
```

- [ ] **Step 2: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Sidebar from "./Sidebar";

describe("Sidebar", () => {
  it("affiche un lien vers chacune des 5 pages", () => {
    render(
      <MemoryRouter initialEntries={["/library"]}>
        <Sidebar />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /Générer/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Bibliothèque/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /À mettre en seed/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Profils/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Réglages/i })).toBeInTheDocument();
  });

  it("marque le lien de la page active avec aria-current", () => {
    render(
      <MemoryRouter initialEntries={["/library"]}>
        <Sidebar />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /Bibliothèque/i })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /Générer/i })).not.toHaveAttribute("aria-current");
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/Sidebar.test.tsx`
Expected: FAIL (`Cannot find module './Sidebar'`)

- [ ] **Step 4: Write minimal implementation**

```tsx
import { FileText, Home, Library, Send, Settings } from "lucide-react";
import { NavLink } from "react-router-dom";

/** Rail lateral fixe (icone + libelle), inspire de la suite *arr
 * (Radarr/Sonarr) -- remplace la nav du haut precedente (App.tsx).
 * Se replie en barre du bas sous 768px (voir classes md: ci-dessous),
 * voir docs/superpowers/specs/2026-09-12-frontend-shell-redesign-design.md. */

const LINKS = [
  { to: "/", label: "Générer", icon: Home, end: true },
  { to: "/library", label: "Bibliothèque", icon: Library, end: false },
  { to: "/seed-queue", label: "À mettre en seed", icon: Send, end: false },
  { to: "/profils", label: "Profils", icon: FileText, end: false },
  { to: "/settings", label: "Réglages", icon: Settings, end: false },
] as const;

function linkClass({ isActive }: { isActive: boolean }) {
  return `flex items-center gap-3 px-4 py-2.5 text-sm transition-colors md:flex-col md:gap-1 md:px-2 md:py-1.5 md:text-xs ${
    isActive
      ? "border-l-2 border-accent bg-surface-2 font-medium text-ink md:border-l-0 md:border-t-2"
      : "text-ink-dim hover:bg-surface-2 hover:text-ink"
  }`;
}

export default function Sidebar() {
  return (
    <nav
      aria-label="Navigation principale"
      className="flex shrink-0 flex-col border-r border-line bg-surface md:fixed md:inset-x-0 md:bottom-0 md:top-auto md:h-auto md:w-full md:flex-row md:justify-around md:border-r-0 md:border-t"
    >
      <div className="px-4 py-4 font-display text-lg font-bold text-ink md:hidden">
        nfogen<span className="font-mono text-sm text-accent">.nfo</span>
      </div>
      {LINKS.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} className={linkClass}>
          <Icon size={18} aria-hidden="true" />
          <span>{label}</span>
        </NavLink>
      ))}
    </nav>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/Sidebar.test.tsx`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
cd frontend && npx tsc -b
git add package.json package-lock.json src/components/Sidebar.tsx src/components/Sidebar.test.tsx
git commit -m "feat: composant Sidebar (rail lateral, remplace la nav du haut)"
```

---

## Task 2: Câbler `Sidebar` dans `App.tsx`

**Files:**
- Modify: `frontend/src/App.tsx:39-66` (fonction `AppShell`)
- Modify: `frontend/src/App.test.tsx` (les liens restent des `role="link"`, aucun changement de nom accessible attendu)

**Interfaces:**
- Consumes: `Sidebar` (Task 1, `export default`).
- Produces: la coquille `AppShell` définitive — `ProfileSelect` (existant) et le contenu des routes restent inchangés, seule l'enveloppe change. Consommé visuellement par toutes les pages (aucune interface de code).

- [ ] **Step 1: Remplacer le corps de `AppShell`**

Remplacer (lignes 39-66 actuelles, du `<header>` pleine largeur + `<nav>` horizontale) par :

```tsx
function AppShell() {
  return (
    <div className="flex min-h-screen bg-bg font-sans text-ink md:flex-col md:pb-16">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-end border-b border-line bg-surface px-4 py-3">
          <ProfileSelect />
        </header>
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6">
          {/* key=pathname : une erreur de rendu sur une page ne doit pas rester
              affichee apres avoir navigue ailleurs -- remonte la limite
              d'erreur (et donc reessaie le rendu) a chaque changement de route. */}
          <ErrorBoundary key={useLocation().pathname}>
            <Routes>
              <Route path="/" element={<GeneratePage />} />
              <Route path="/profils" element={<ProfilesListPage />} />
              <Route path="/profiles/new" element={<ProfileEditorPage mode="create" />} />
              <Route path="/profiles/:name" element={<ProfileEditorPage mode="edit" />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/library" element={<LibraryPage />} />
              <Route path="/seed-queue" element={<SeedQueuePage />} />
            </Routes>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
```

Ajouter l'import `Sidebar` en haut du fichier (à côté des autres imports de composants) :

```tsx
import Sidebar from "./components/Sidebar";
```

- [ ] **Step 2: Run existing App tests to verify no regression**

Run: `cd frontend && npx vitest run src/App.test.tsx`
Expected: 4 PASS (inchangé — les tests vérifient des `role="link"`/`role="combobox"` par nom accessible, indépendants de la position visuelle)

- [ ] **Step 3: Typecheck + build**

Run: `cd frontend && npx tsc -b && npm run build`
Expected: aucune erreur

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.tsx
git commit -m "feat: App.tsx utilise Sidebar au lieu de la nav du haut"
```

---

## Task 3: Composant `PageToolbar`

**Files:**
- Create: `frontend/src/components/PageToolbar.tsx`
- Test: `frontend/src/components/PageToolbar.test.tsx`

**Interfaces:**
- Consumes: rien.
- Produces: `export default function PageToolbar(props: { title: string; subtitle?: string; children?: React.ReactNode }): JSX.Element` — `children` reçoit les contrôles (recherche/filtres/boutons) de la page appelante. Consommé par Task 6 (`LibraryPage.tsx`).

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import PageToolbar from "./PageToolbar";

describe("PageToolbar", () => {
  it("affiche le titre, le sous-titre optionnel et les enfants", () => {
    render(
      <PageToolbar title="Bibliothèque" subtitle="Dernière synchro : il y a 1 min">
        <button>Rafraîchir</button>
      </PageToolbar>,
    );
    expect(screen.getByRole("heading", { name: "Bibliothèque" })).toBeInTheDocument();
    expect(screen.getByText("Dernière synchro : il y a 1 min")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Rafraîchir" })).toBeInTheDocument();
  });

  it("fonctionne sans sous-titre", () => {
    render(<PageToolbar title="Réglages" />);
    expect(screen.getByRole("heading", { name: "Réglages" })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/PageToolbar.test.tsx`
Expected: FAIL (`Cannot find module './PageToolbar'`)

- [ ] **Step 3: Write minimal implementation**

```tsx
import type { ReactNode } from "react";

/** Barre d'outils commune a toutes les pages : titre + sous-titre optionnel
 * a gauche, controles (recherche/filtres/actions) a droite -- jamais
 * d'element flottant au milieu du contenu (retour utilisateur, 2026-09-12).
 * Sous le breakpoint `sm`, les controles passent en dessous, pleine
 * largeur, plutot que de se compresser horizontalement. */
export default function PageToolbar({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children?: ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center">
      <div>
        <h1 className="font-display text-xl font-semibold text-ink">{title}</h1>
        {subtitle && <p className="text-xs text-ink-dim">{subtitle}</p>}
      </div>
      {children && <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">{children}</div>}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/PageToolbar.test.tsx`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PageToolbar.tsx frontend/src/components/PageToolbar.test.tsx
git commit -m "feat: composant PageToolbar (titre + controles, jamais flottant au milieu)"
```

---

## Task 4: Composant `Drawer`

**Files:**
- Create: `frontend/src/components/Drawer.tsx`
- Test: `frontend/src/components/Drawer.test.tsx`

**Interfaces:**
- Consumes: rien.
- Produces: `export default function Drawer(props: { onClose: () => void; children: React.ReactNode }): JSX.Element`. Consommé par Task 6 (`UploadPrepPanel.tsx`, dont le rendu racine change de forme).

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Drawer from "./Drawer";

describe("Drawer", () => {
  it("affiche son contenu et un bouton de fermeture", async () => {
    const onClose = vi.fn();
    render(
      <Drawer onClose={onClose}>
        <p>Contenu du tiroir</p>
      </Drawer>,
    );
    expect(screen.getByText("Contenu du tiroir")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /fermer/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("appelle onClose au clic sur le fond assombri", async () => {
    const onClose = vi.fn();
    render(
      <Drawer onClose={onClose}>
        <p>Contenu</p>
      </Drawer>,
    );
    await userEvent.click(screen.getByTestId("drawer-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/Drawer.test.tsx`
Expected: FAIL (`Cannot find module './Drawer'`)

- [ ] **Step 3: Write minimal implementation**

```tsx
import { X } from "lucide-react";
import type { ReactNode } from "react";

/** Tiroir lateral droit -- remplace le patron d'overlay centre utilise
 * jusqu'ici (ex: UploadPrepPanel), qui coupait la lecture du contenu en
 * dessous (retour utilisateur, 2026-09-12). Coherent avec le rail a
 * gauche (Sidebar) : les panneaux d'action arrivent desormais du cote
 * oppose. Pleine largeur sur mobile (< 640px). */
export default function Drawer({ onClose, children }: { onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div
        data-testid="drawer-backdrop"
        className="absolute inset-0 bg-ink/50"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-line bg-surface p-4 shadow-lg sm:max-w-lg">
        <button
          type="button"
          onClick={onClose}
          aria-label="Fermer"
          className="self-end rounded-md p-1 text-ink-dim hover:bg-surface-2 hover:text-ink"
        >
          <X size={18} />
        </button>
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/Drawer.test.tsx`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Drawer.tsx frontend/src/components/Drawer.test.tsx
git commit -m "feat: composant Drawer (tiroir lateral droit, remplace l'overlay centre)"
```

---

## Task 5: Composant `InlineBanner`

**Files:**
- Create: `frontend/src/components/InlineBanner.tsx`
- Test: `frontend/src/components/InlineBanner.test.tsx`

**Interfaces:**
- Consumes: rien.
- Produces: `export default function InlineBanner(props: { children: React.ReactNode }): JSX.Element` — un conteneur ; chaque ligne d'alerte est un enfant direct fourni par l'appelant (pas de logique de liste interne, reste simple). Consommé par Task 6 (`LibraryPage.tsx`, remplace le bloc "Packs disponibles" actuel).

- [ ] **Step 1: Write the failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import InlineBanner from "./InlineBanner";

describe("InlineBanner", () => {
  it("affiche les enfants fournis", () => {
    render(
      <InlineBanner>
        <p>Braquo — INTEGRALE disponible</p>
      </InlineBanner>,
    );
    expect(screen.getByText("Braquo — INTEGRALE disponible")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/InlineBanner.test.tsx`
Expected: FAIL (`Cannot find module './InlineBanner'`)

- [ ] **Step 3: Write minimal implementation**

```tsx
import type { ReactNode } from "react";

/** Bandeau fin ancre AU-DESSUS du contenu concerne (jamais au milieu --
 * retour utilisateur, 2026-09-12, "les pack disponible en plein milieu
 * qui casse le visuel"). Une ligne par element fourni par l'appelant. */
export default function InlineBanner({ children }: { children: ReactNode }) {
  return <div className="mb-3 divide-y divide-line rounded-md border border-line bg-surface-2">{children}</div>;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/InlineBanner.test.tsx`
Expected: 1 PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/InlineBanner.tsx frontend/src/components/InlineBanner.test.tsx
git commit -m "feat: composant InlineBanner (bandeau d'alerte ancre, jamais au milieu du contenu)"
```

---

## Task 6: Migrer `LibraryPage.tsx` (premier consommateur complet)

**Files:**
- Modify: `frontend/src/pages/LibraryPage.tsx` (bloc titre/actions lignes ~525-576, bloc packs lignes ~841-895, mount du panneau lignes ~1061-1075)
- Modify: `frontend/src/components/UploadPrepPanel.tsx:350-358` (racine du rendu)
- Modify: `frontend/src/pages/LibraryPage.test.tsx` / `frontend/src/components/UploadPrepPanel.test.tsx` (adapter les sélecteurs DOM qui ciblaient l'ancien overlay, si nécessaire)

**Interfaces:**
- Consumes: `PageToolbar` (Task 3), `Drawer` (Task 4), `InlineBanner` (Task 5).
- Produces: rien de nouveau — dernière tâche du plan.

- [ ] **Step 1: Remplacer le bloc titre/actions par `PageToolbar`**

Remplacer (le `<div className="flex items-center justify-between">` actuel contenant `<h1>`/sous-titre/select/checkbox/boutons, lignes ~526-576) par :

```tsx
<PageToolbar title="Bibliothèque" subtitle={`Dernière synchro : ${formatSyncedAt(syncedAt)}`}>
  <select
    value={only}
    onChange={(e) => setOnly(e.target.value as "" | "movies" | "series")}
    disabled={starting || running}
    aria-label="Bibliothèque à scanner"
    className="rounded-md border border-line-strong bg-surface px-2 py-2 text-sm text-ink"
  >
    <option value="">Films + séries</option>
    <option value="movies">Films seulement</option>
    <option value="series">Séries seulement</option>
  </select>
  {hasPreviousScan && (
    <label
      className="flex items-center gap-1.5 text-sm text-ink-dim"
      title="Reprend les titres déjà couverts et inchangés du dernier scan sans les réinterroger sur C411 — plus rapide."
    >
      <input
        type="checkbox"
        checked={incremental}
        onChange={(e) => setIncremental(e.target.checked)}
        disabled={starting || running}
        className="h-4 w-4 rounded border-line-strong"
      />
      Scan rapide
    </label>
  )}
  <button
    type="button"
    onClick={handleRefresh}
    disabled={refreshing}
    className="rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink hover:bg-surface-hover disabled:opacity-50"
  >
    {refreshing ? "Rafraîchissement…" : "Rafraîchir"}
  </button>
  <button
    type="button"
    onClick={handleExportCsv}
    disabled={!items || items.length === 0}
    className="rounded-md border border-line-strong px-4 py-2 text-sm text-ink hover:bg-surface-2 disabled:opacity-50"
  >
    Export CSV
  </button>
</PageToolbar>
```

(le reste des boutons/contrôles déjà présents dans l'ancien bloc — `starting`/`running`/lancement de scan — suit le même patron : déplacés tels quels comme enfants de `PageToolbar`, aucune logique changée)

Ajouter l'import en haut du fichier :

```tsx
import PageToolbar from "../components/PageToolbar";
```

- [ ] **Step 2: Remplacer le bloc "Packs disponibles" par `InlineBanner`**

Remplacer (lignes ~841-895 actuelles) par :

```tsx
{seasonPacks.length > 0 && (
  <InlineBanner>
    {seasonPacks.map((pack) => {
      const seasons = seasonsForPack(pack);
      const label = pack.is_full_series
        ? "INTEGRALE"
        : `S${String(pack.season_numbers[0]).padStart(2, "0")}S${String(
            pack.season_numbers[pack.season_numbers.length - 1],
          ).padStart(2, "0")}`;
      return (
        <div
          key={`${pack.sonarr_series_id}-${pack.season_numbers.join("-")}`}
          className="flex items-center justify-between px-3 py-2 text-sm"
        >
          <span>
            {pack.title} — {label} ({pack.team})
          </span>
          <button
            type="button"
            disabled={seasons === null}
            title={
              seasons === null
                ? "Certaines saisons de ce pack ne sont pas visibles dans la page/le filtre actuel."
                : undefined
            }
            onClick={() => {
              if (seasons === null) return;
              setActiveUpload({
                title: `${pack.title} ${label}`,
                localPaths: seasons.flatMap((s) => s.local_paths),
                mediaType: "series",
                radarrMovieId: null,
                sonarrSeriesId: pack.sonarr_series_id,
                tmdbId: null,
                tvdbId: null,
                genre: null,
                seasonNumber: null,
                seasonPack: { title: pack.title, team: pack.team, is_full_series: pack.is_full_series, seasons },
              });
            }}
            className="rounded-md border border-line-strong px-3 py-1.5 text-xs text-ink hover:bg-surface-2 disabled:opacity-50"
          >
            Préparer le pack
          </button>
        </div>
      );
    })}
  </InlineBanner>
)}
```

Ajouter l'import :

```tsx
import InlineBanner from "../components/InlineBanner";
```

- [ ] **Step 3: Run LibraryPage tests to verify no regression**

Run: `cd frontend && npx vitest run src/pages/LibraryPage.test.tsx`
Expected: 41 PASS (les tests ciblent du texte/des rôles ARIA, pas la structure DOM précise — doivent passer sans modification)

- [ ] **Step 4: Convertir `UploadPrepPanel` en tiroir**

Dans `frontend/src/components/UploadPrepPanel.tsx`, remplacer la racine du rendu (actuellement lignes 350-358, un `<div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink/50 p-4 sm:items-center">` contenant un second `<div className="max-h-[90vh] w-full max-w-2xl ...">`) par :

```tsx
return (
  <Drawer onClose={onClose}>
    {/* Contenu existant du panneau (titre, formulaire, aperçu...) INCHANGÉ --
        seule l'enveloppe change, Drawer gère déjà le fond assombri et le
        bouton de fermeture. */}
```

(fermer avec `</Drawer>` à la place de l'actuel double `</div></div>` de fin de fonction)

Ajouter l'import :

```tsx
import Drawer from "./Drawer";
```

Retirer, dans le JSX existant, le bouton de fermeture ad hoc du panneau s'il y en avait un dupliqué avec celui du `Drawer` (vérifier autour de `onClose()` ligne 264 — si c'est un bouton "Annuler"/"Fermer" distinct dans le corps du formulaire, le garder, seul le X en coin est fourni par `Drawer`).

- [ ] **Step 5: Run UploadPrepPanel tests to verify no regression**

Run: `cd frontend && npx vitest run src/components/UploadPrepPanel.test.tsx`
Expected: PASS (si un test cible spécifiquement l'ancienne classe `fixed inset-0` ou la structure de l'overlay, l'adapter au nouveau rendu de `Drawer` — sinon aucun changement)

- [ ] **Step 6: Typecheck, build, suite complète**

```bash
cd frontend && npx tsc -b && npx vitest run && npm run build
```
Expected: tsc clean, tous les tests passent, build sans erreur

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/LibraryPage.tsx frontend/src/pages/LibraryPage.test.tsx frontend/src/components/UploadPrepPanel.tsx frontend/src/components/UploadPrepPanel.test.tsx
git commit -m "feat: LibraryPage utilise PageToolbar/InlineBanner/Drawer (premiere page migree)"
```

---

## Self-Review

**Spec coverage :** rail latéral *arr-style (Task 1-2) ✅ ; barre d'outils par page, jamais d'élément flottant au milieu (Task 3, 6) ✅ ; couleurs strictement reprises de l'existant (toutes les tasks, aucune nouvelle valeur de couleur introduite) ✅ ; icônes Lucide (Task 1, 4) ✅ ; bannières ancrées au-dessus du contenu (Task 5, 6) ✅ ; panneaux superposés -> tiroir latéral (Task 4, 6) ✅ ; responsive rail -> barre du bas (Task 1, classes `md:`) ✅. **Hors périmètre de ce plan, explicitement noté** (Global Constraints) : `SeedQueuePage`/`SettingsPage`/`GeneratePage`/`ProfilesListPage`/`ProfileEditorPage` — héritent du rail via `App.tsx` mais leur contenu interne (encadré inutile, position du bloc connexion) est un plan de suivi.

**Placeholder scan :** aucun `TBD`/`TODO` ; chaque step contient du code réel.

**Type consistency :** `Sidebar` (Task 1, `export default function Sidebar()`) importé identiquement dans `App.tsx` (Task 2). `PageToolbar({title, subtitle?, children?})` (Task 3) utilisé avec les mêmes props dans `LibraryPage.tsx` (Task 6). `Drawer({onClose, children})` (Task 4) utilisé à l'identique dans `UploadPrepPanel.tsx` (Task 6, `onClose` déjà une prop existante du composant, pas de nouveau nom introduit). `InlineBanner({children})` (Task 5) utilisé sans prop supplémentaire dans `LibraryPage.tsx` (Task 6).
