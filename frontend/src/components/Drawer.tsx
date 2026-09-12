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
