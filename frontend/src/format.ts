/** Formate une taille en octets en unite lisible (Go/Mo/Ko) -- partage
 * entre LibraryPage et SeedQueuePage (retour utilisateur, 2026-09-09 :
 * colonne "Taille" ajoutee a la Bibliotheque, meme besoin que le tableau
 * "En cours de seed" existant). */
export function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} Go`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} Mo`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} Ko`;
  return `${bytes} o`;
}
