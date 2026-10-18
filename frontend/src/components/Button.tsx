import type { ButtonHTMLAttributes } from "react";
import { type ButtonSize, type ButtonVariant, buttonClass } from "./buttonClass";

/** Bouton commun -- voir buttonClass.ts pour les variantes et le pourquoi
 * du retour a l'appui. `type="button"` par defaut : aucun bouton de
 * l'application ne soumet de formulaire natif. */
export default function Button({
  variant = "secondary",
  size = "md",
  className,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; size?: ButtonSize }) {
  return <button type={type} className={buttonClass(variant, size, className)} {...props} />;
}
