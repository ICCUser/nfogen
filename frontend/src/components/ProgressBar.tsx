/** Barre de progression commune (audit front 2026-10-14, lot 7). Avant,
 * quatre copies animaient `width` (`transition-all`) : recalcul de mise en
 * page a chaque image, et une barre qui SAUTAIT a chaque nouvelle reponse
 * du polling.
 *
 * - Remplissage par `scale` horizontal (composite, pas de mise en page),
 *   ancre a gauche.
 * - Transition LINEAIRE de duree calee sur l'intervalle de polling
 *   (`pollMs`) : la barre atteint la nouvelle valeur au moment ou la
 *   suivante arrive -- mouvement continu au lieu de paliers. Gardee en
 *   mouvement reduit : une barre qui avance n'est pas un deplacement
 *   vestibulaire.
 * - `value === null` (total encore inconnu) : etat indetermine, un segment
 *   qui balaie la piste -- au lieu d'un "10 %" fige qui ment. En
 *   mouvement reduit : segment immobile, aucune animation.
 * - Semantique `role="progressbar"` + `aria-valuenow` (absent si
 *   indetermine). Pas de region live : le lecteur d'ecran lit la valeur a
 *   la demande au lieu d'annoncer chaque pourcentage. */
export default function ProgressBar({
  value,
  label,
  pollMs = 1500,
  size = "md",
}: {
  /** 0-100, ou null si la progression est inconnue. */
  value: number | null;
  /** Nom accessible (ce qui progresse). */
  label: string;
  /** Intervalle de rafraichissement de `value`, en ms. */
  pollMs?: number;
  size?: "sm" | "md";
}) {
  const clamped = value === null ? null : Math.min(100, Math.max(0, value));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped === null ? undefined : Math.round(clamped)}
      className={`relative w-full overflow-hidden rounded-full bg-surface-2 ${size === "sm" ? "h-1.5" : "h-2"}`}
    >
      {clamped === null ? (
        <div className="absolute inset-y-0 left-0 w-2/5 rounded-full bg-accent/70 animate-progress-indeterminate motion-reduce:animate-none motion-reduce:left-[30%]" />
      ) : (
        <div
          className="h-full origin-left rounded-full bg-accent transition-[scale] ease-linear"
          style={{ scale: `${clamped / 100} 1`, transitionDuration: `${Math.max(0, pollMs - 100)}ms` }}
        />
      )}
    </div>
  );
}
