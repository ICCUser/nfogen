#!/usr/bin/env bash
# Mise a jour de nfogen : recupere les derniers changements (git pull) puis
# relance l'installation -- qui ne fait que remplacer le CODE applicatif
# (/opt/nfogen), jamais la configuration (/etc/nfogen) ni les profils
# utilisateur (/var/lib/nfogen), cf. install.sh. Le token API existant
# n'est jamais regenere, le service est juste rebuilde et redemarre.
#
# A lancer en root, depuis la MEME copie clonee qu'a l'installation :
#
#     cd nfogen
#     sudo ./scripts/update.sh
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Ce script doit etre lance en root : sudo ./scripts/update.sh" >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_DIR}"

if [[ -d .git ]]; then
    echo "==> git pull (${REPO_DIR})"
    git pull --ff-only
else
    echo "Pas un depot git clone (${REPO_DIR}) : recuperez la derniere version"
    echo "vous-meme (git clone ou archive) avant de relancer ce script." >&2
    exit 1
fi

echo "==> Reinstallation (code applicatif uniquement, cf. install.sh)"
exec "${REPO_DIR}/scripts/install.sh"
