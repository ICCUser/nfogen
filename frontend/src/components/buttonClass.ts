/** Styles de bouton communs (audit front 2026-10-14, lot 2) -- remplace la quarantaine
 * de chaines de classes copiees-collees qui derivaient (px-3/px-4,
 * text-xs/text-sm...) et n'avaient AUCUN retour a l'appui : `hover:` n'existe
 * pas au tactile. Retour immediat sur pointer-down (`active:`), jamais
 * seulement au relachement ; `not-disabled:` evite qu'un bouton desactive
 * reagisse. Le leger rapetissement est reserve a `motion-safe:` -- en
 * mouvement reduit, il reste le changement de fond/opacite, qui suffit a
 * signaler l'appui sans deplacement. Le focus clavier est gere globalement
 * (index.css, :focus-visible), commun a tous les elements interactifs. */

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "danger"
  | "danger-secondary"
  | "link"
  | "link-danger"
  | "link-muted";
export type ButtonSize = "sm" | "md";

const PRESS = "transition-[scale,opacity,background-color] duration-100 ease-out motion-safe:not-disabled:active:scale-[0.97]";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: `${PRESS} rounded-md bg-accent font-medium text-surface hover:opacity-90 not-disabled:active:opacity-80`,
  secondary: `${PRESS} rounded-md border border-line-strong text-ink hover:bg-surface-2 not-disabled:active:bg-line`,
  danger: `${PRESS} rounded-md bg-crit font-medium text-surface hover:opacity-90 not-disabled:active:opacity-80`,
  "danger-secondary": `${PRESS} rounded-md border border-crit text-crit hover:bg-crit-bg not-disabled:active:opacity-70`,
  // Liens d'action dans le texte : pas de rapetissement (decalerait la
  // ligne), seulement un estompement a l'appui.
  link: "text-accent-ink underline underline-offset-2 transition-opacity duration-100 not-disabled:active:opacity-60",
  "link-danger": "text-crit underline underline-offset-2 transition-opacity duration-100 not-disabled:active:opacity-60",
  "link-muted": "text-ink-faint underline underline-offset-2 transition-[color,opacity] duration-100 hover:text-ink not-disabled:active:opacity-60",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
};

/** Classes d'un bouton, pour styler un autre element (ex. un <Link>) a
 * l'identique. Les variantes `link*` n'ont pas de taille : elles heritent
 * de celle du texte environnant. */
export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", extra?: string): string {
  const isLink = variant.startsWith("link");
  return [VARIANTS[variant], isLink ? null : SIZES[size], "disabled:cursor-not-allowed disabled:opacity-50", extra]
    .filter(Boolean)
    .join(" ");
}
