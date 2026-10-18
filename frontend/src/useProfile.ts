import { createContext, useContext } from "react";

/** Contexte du profil actif et son hook d'acces -- dans un fichier a part
 * de <ProfileProvider> (ProfileContext.tsx) : le rechargement a chaud de
 * Vite (Fast Refresh) ne s'applique qu'aux fichiers qui n'exportent QUE des
 * composants (oxlint react/only-export-components). */
export interface ProfileContextValue {
  profile: string;
  setProfile: (profile: string) => void;
  profiles: Record<string, string[]>;
  /** Nom lisible du profil actif (rules.json -> tracker.display_name),
   * repli sur le nom du profil lui-meme si non declare. */
  displayName: string;
}

export const ProfileContext = createContext<ProfileContextValue | null>(null);

export function useProfile(): ProfileContextValue {
  const ctx = useContext(ProfileContext);
  if (!ctx) throw new Error("useProfile doit être utilisé à l'intérieur de <ProfileProvider>.");
  return ctx;
}
