import { type ReactNode, useEffect, useRef, useState } from "react";
import Button from "./Button";
import type { ButtonSize, ButtonVariant } from "./buttonClass";

/** Confirmation SUR PLACE d'une action irreversible (audit front
 * 2026-10-14, lot 4) -- remplace window.confirm(), qui bloque la page,
 * ignore le theme sombre et affiche "localhost:8000 indique...".
 *
 * Premier clic : le bouton laisse place a la question + deux choix, au meme
 * endroit (le regard n'a pas a chercher une boite au centre de l'ecran). Le
 * focus va sur "Annuler" -- l'option sans risque : deux Entree d'affilee ne
 * declenchent jamais l'action. Echap annule SANS remonter (dans un tiroir,
 * Echap fermerait sinon le tiroir entier).
 *
 * A reserver aux actions reellement destructives ou publiques : en abuser
 * apprend a cliquer sans lire (principe Agency, voir l'audit). */
export default function ConfirmButton({
  children,
  question,
  confirmLabel,
  cancelLabel = "Annuler",
  onConfirm,
  variant = "secondary",
  size = "md",
  disabled,
  title,
}: {
  children: ReactNode;
  question: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  variant?: ButtonVariant;
  size?: ButtonSize;
  disabled?: boolean;
  title?: string;
}) {
  const [armed, setArmed] = useState(false);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  // Ne rend le focus au declencheur qu'apres une annulation (pas au
  // premier rendu, ni apres confirmation : l'action peut avoir change
  // l'interface).
  const restoreFocus = useRef(false);

  useEffect(() => {
    if (armed) cancelRef.current?.focus();
    else if (restoreFocus.current) {
      restoreFocus.current = false;
      triggerRef.current?.focus();
    }
  }, [armed]);

  function cancel() {
    restoreFocus.current = true;
    setArmed(false);
  }

  if (!armed) {
    return (
      <Button ref={triggerRef} variant={variant} size={size} disabled={disabled} title={title} onClick={() => setArmed(true)}>
        {children}
      </Button>
    );
  }

  return (
    <span
      role="group"
      aria-label={question}
      className="inline-flex flex-wrap items-center gap-2 rounded-md border border-crit bg-crit-bg px-2 py-1"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          cancel();
        }
      }}
    >
      <span className="text-xs font-medium text-crit">{question}</span>
      <Button
        variant="danger"
        size="sm"
        onClick={() => {
          setArmed(false);
          onConfirm();
        }}
      >
        {confirmLabel}
      </Button>
      <Button ref={cancelRef} variant="secondary" size="sm" onClick={cancel}>
        {cancelLabel}
      </Button>
    </span>
  );
}
