import { X } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";

/** Duree d'entree/sortie (ms) -- doit rester alignee sur `duration-300`
 * ci-dessous : sert de filet si `transitionend` ne vient jamais (onglet en
 * arriere-plan, transition annulee, environnement de test). */
const TRANSITION_MS = 300;

/** Tiroir lateral droit -- remplace le patron d'overlay centre utilise
 * jusqu'ici (ex: UploadPrepPanel), qui coupait la lecture du contenu en
 * dessous (retour utilisateur, 2026-09-12). Coherent avec le rail a
 * gauche (Sidebar) : les panneaux d'action arrivent desormais du cote
 * oppose. Pleine largeur sur mobile (< 640px).
 *
 * Audit front 2026-10-14, lot 3 :
 * - `<dialog>` natif + showModal() : focus confine au tiroir, arriere-plan
 *   inerte, role dialog porte par le tiroir lui-meme (`label`).
 * - Entre ET sort par la droite (meme chemin dans les deux sens), le fond
 *   assombri en fondu. Transition CSS (pas d'images-cles) : reouvrir
 *   pendant la fermeture repart de la position courante, sans saut.
 *   L'etat de depart de l'entree vient de `starting:` (@starting-style) :
 *   pas d'attente d'une image (requestAnimationFrame), qui laisserait le
 *   tiroir hors ecran tant que l'onglet n'est pas peint.
 * - Mouvement reduit : simple fondu, aucun deplacement.
 * - Le focus revient a l'element qui avait ouvert le tiroir.
 *
 * `onClose` est une DEMANDE de fermeture (X, fond, Echap) : l'appelant
 * peut la refuser (garde-fou) en laissant `open` a true. `onExited` est
 * appele une fois l'animation de sortie terminee -- c'est la que
 * l'appelant demonte le contenu. */
export default function Drawer({
  open = true,
  onClose,
  onExited,
  label,
  children,
}: {
  open?: boolean;
  onClose: () => void;
  onExited?: () => void;
  label: string;
  children: ReactNode;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const onExitedRef = useRef(onExited);
  onExitedRef.current = onExited;

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      if (!dialog.open) {
        returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        dialog.showModal();
      }
      panelRef.current?.focus();
      return;
    }
    // Monte deja ferme : rien a animer ni a signaler.
    if (!dialog.open) return;
    const panel = panelRef.current;
    let done = false;
    function finish() {
      if (done) return;
      done = true;
      dialog?.close();
      returnFocusRef.current?.focus();
      onExitedRef.current?.();
    }
    function onTransitionEnd(e: TransitionEvent) {
      if (e.target === panel) finish();
    }
    panel?.addEventListener("transitionend", onTransitionEnd);
    const fallback = window.setTimeout(finish, TRANSITION_MS + 100);
    return () => {
      panel?.removeEventListener("transitionend", onTransitionEnd);
      window.clearTimeout(fallback);
    };
  }, [open]);

  // Securite au demontage brutal (ex. changement de page) : ne jamais
  // laisser un dialog modal ouvert, qui rendrait toute la page inerte.
  useEffect(() => {
    const dialog = dialogRef.current;
    return () => {
      if (dialog?.open) dialog.close();
    };
  }, []);

  return (
    <dialog
      ref={dialogRef}
      aria-label={label}
      // Echap : traite au keydown, AVANT la fermeture native du navigateur,
      // pour passer par le meme garde-fou que X/fond (onClose).
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          onClose();
        }
      }}
      // Autres demandes de fermeture natives (ex. bouton retour Android).
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      // Fermeture native non sollicitee alors que l'appelant veut toujours
      // le tiroir ouvert (ex. anti-abus de Chrome apres plusieurs Echap
      // refuses) : on le rouvre plutot que de desynchroniser l'etat.
      onClose={() => {
        if (open && dialogRef.current && !dialogRef.current.open) dialogRef.current.showModal();
      }}
      className="fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none overflow-hidden border-0 bg-transparent p-0 backdrop:bg-transparent"
    >
      <div
        data-testid="drawer-backdrop"
        className={`absolute inset-0 bg-ink/50 transition-opacity duration-300 ease-out motion-reduce:duration-200 ${
          open ? "opacity-100 starting:opacity-0" : "opacity-0"
        }`}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        data-testid="drawer-panel"
        tabIndex={-1}
        className={`absolute inset-y-0 right-0 flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-line bg-surface p-4 shadow-lg outline-none sm:max-w-lg transition-[translate,opacity] duration-300 ease-[cubic-bezier(0.32,0.72,0,1)] motion-reduce:duration-200 motion-reduce:ease-out ${
          open
            ? "translate-x-0 opacity-100 starting:translate-x-full motion-reduce:starting:translate-x-0 motion-reduce:starting:opacity-0"
            : "translate-x-full motion-reduce:translate-x-0 motion-reduce:opacity-0"
        }`}
      >
        <button
          type="button"
          onClick={onClose}
          aria-label="Fermer"
          className="self-end rounded-md p-1 text-ink-dim transition-[scale,background-color] duration-100 hover:bg-surface-2 hover:text-ink active:bg-line motion-safe:active:scale-90"
        >
          <X size={18} />
        </button>
        {children}
      </div>
    </dialog>
  );
}
