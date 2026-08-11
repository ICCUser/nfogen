#!/usr/bin/env bash
# Installation native de nfogen sur Debian/Ubuntu : paquets systeme, venv
# Python dedie, build du frontend, service systemd. Pas de Docker.
#
# A lancer en root, depuis une copie CLONEE du depot (jamais en pipant
# `curl | bash` a l'aveugle -- lis ce script avant de l'executer) :
#
#     git clone https://github.com/ICCUser/nfogen.git
#     cd nfogen
#     sudo ./scripts/install.sh
#
# Idempotent : relancable sans rien perdre, c'est aussi le mecanisme de MISE
# A JOUR (cf. scripts/update.sh, qui fait juste `git pull` puis relance ce
# script). Le code applicatif (/opt/nfogen) est entierement remplace a chaque
# execution -- mais JAMAIS la config (/etc/nfogen) ni les donnees utilisateur
# (/var/lib/nfogen, profils crees/modifies via l'interface) : ces deux
# dossiers sont physiquement separes du code, donc un `rsync --delete` qui
# nettoie le code ne peut pas les atteindre par erreur. Le token API existant
# n'est jamais regenere.
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "Ce script doit etre lance en root : sudo ./scripts/install.sh" >&2
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Ce script suppose une distribution Debian/Ubuntu (apt-get introuvable)." >&2
    echo "Pour les autres distributions, voir l'image Docker (README.md)." >&2
    exit 1
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="/opt/nfogen"          # code applicatif -- remplace a chaque run
CONFIG_DIR="/etc/nfogen"           # configuration -- jamais touchee par rsync
DATA_DIR="/var/lib/nfogen"         # donnees utilisateur -- jamais touchee par rsync
PROFILES_DIR="${DATA_DIR}/profiles"
ENV_FILE="${CONFIG_DIR}/nfogen.env"
SERVICE_USER="nfogen"
SERVICE_NAME="nfogen"
NODE_MAJOR="22"
# nfogen (useradd --no-create-home) n'a pas de /home/nfogen : sans HOME
# explicite, pip/npm essaient d'y ecrire leur cache et echouent (EACCES).
# Reutilise DATA_DIR (persistant, jamais touche par une mise a jour).
NFOGEN_HOME="${DATA_DIR}/home"

run_as_nfogen() {
    sudo -u "${SERVICE_USER}" env HOME="${NFOGEN_HOME}" "$@"
}

echo "==> Paquets systeme (Python, libmediainfo, rsync, openssl...)"
apt-get update
apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip libmediainfo0v5 rsync openssl ca-certificates curl gnupg

# Les depots Debian/Ubuntu fournissent souvent un Node.js trop ancien pour
# le frontend (Vite 8 / React 19 exigent Node >= 20). On utilise le depot
# officiel NodeSource (https://github.com/nodesource/distributions), la
# methode documentee par le projet Node.js lui-meme pour avoir une version
# recente sur ces distributions -- pas une source tierce improvisee.
CURRENT_NODE_MAJOR="0"
if command -v node >/dev/null 2>&1; then
    CURRENT_NODE_MAJOR="$(node -v | sed -E 's/^v([0-9]+).*/\1/')"
fi
if [[ "${CURRENT_NODE_MAJOR}" -lt "${NODE_MAJOR}" ]]; then
    echo "==> Node.js absent ou trop ancien (v${CURRENT_NODE_MAJOR}) : depot NodeSource (Node ${NODE_MAJOR}.x)"
    curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
    apt-get install -y --no-install-recommends nodejs
fi

echo "==> Utilisateur systeme dedie (${SERVICE_USER}, sans shell de connexion)"
if ! id "${SERVICE_USER}" >/dev/null 2>&1; then
    useradd --system --shell /usr/sbin/nologin --no-create-home "${SERVICE_USER}"
fi

echo "==> Donnees persistantes (${DATA_DIR}) -- jamais effacees par une mise a jour"
mkdir -p "${PROFILES_DIR}" "${NFOGEN_HOME}"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${DATA_DIR}"

echo "==> Copie du code applicatif vers ${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
rsync -a --delete \
    --exclude ".git" --exclude ".venv" --exclude "__pycache__" --exclude "*.egg-info" \
    --exclude ".pytest_cache" --exclude ".ruff_cache" --exclude "node_modules" --exclude "dist" \
    --exclude "tests/Video test" \
    "${REPO_DIR}/" "${INSTALL_DIR}/"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

echo "==> Environnement Python (venv dedie + nfogen[api])"
run_as_nfogen python3 -m venv "${INSTALL_DIR}/.venv"
run_as_nfogen "${INSTALL_DIR}/.venv/bin/pip" install --no-cache-dir --upgrade pip
run_as_nfogen "${INSTALL_DIR}/.venv/bin/pip" install --no-cache-dir "${INSTALL_DIR}[api]"

echo "==> Build du frontend (npm ci && npm run build)"
run_as_nfogen npm --prefix "${INSTALL_DIR}/frontend" ci
run_as_nfogen npm --prefix "${INSTALL_DIR}/frontend" run build

echo "==> Configuration (${CONFIG_DIR})"
mkdir -p "${CONFIG_DIR}"
if [[ ! -f "${ENV_FILE}" ]]; then
    echo "    Generation du token API (premiere installation)"
    TOKEN="$(openssl rand -hex 24)"
    cat > "${ENV_FILE}" <<EOF
# Genere par scripts/install.sh -- modifiable, relu a chaque demarrage du
# service (cf. EnvironmentFile dans /etc/systemd/system/${SERVICE_NAME}.service).
# Variables documentees dans README.md (section "Service HTTP"). Ce fichier
# n'est JAMAIS regenere ni efface par une mise a jour (scripts/update.sh).
NFOGEN_API_TOKEN=${TOKEN}
NFOGEN_PROFILES_DIR=${PROFILES_DIR}
NFOGEN_FRONTEND_DIST=${INSTALL_DIR}/frontend/dist
EOF
else
    echo "    ${ENV_FILE} existe deja : conserve tel quel (token non regenere)"
fi
chown "${SERVICE_USER}:${SERVICE_USER}" "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

echo "==> Service systemd (${SERVICE_NAME})"
cat > "/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=nfogen - generation de fichiers NFO
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${INSTALL_DIR}/.venv/bin/uvicorn nfogen.api:app --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${DATA_DIR}
# PrivateTmp : /generate (upload multipart) ecrit dans un repertoire
# temporaire (tempfile.TemporaryDirectory, nfogen/api.py) -- sans ceci,
# ProtectSystem=strict rendrait /tmp inaccessible en ecriture et casserait
# l'upload. Donne au service son propre /tmp isole, pas le /tmp du systeme.
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

IP_ADDR="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo "==> Installation/mise a jour terminee."
echo "    Statut  : systemctl status ${SERVICE_NAME}"
echo "    Logs    : journalctl -u ${SERVICE_NAME} -f"
echo "    URL     : http://${IP_ADDR:-<ip-serveur>}:8000"
echo "    Config  : ${ENV_FILE} (token API...)"
echo "    Profils : ${PROFILES_DIR} (persistant, jamais touche par une mise a jour)"
echo "    Pour appliquer un changement de ${ENV_FILE} : systemctl restart ${SERVICE_NAME}"
echo "    Pour mettre a jour plus tard : sudo ./scripts/update.sh (depuis ${REPO_DIR})"
