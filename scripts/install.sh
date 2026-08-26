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

# Valeur de la cle $1 dans le fichier $2 ("" si absente ou fichier absent) --
# sert a relire un choix TLS deja persiste par une execution precedente.
_get_env_var() {
    [[ -f "$2" ]] && sed -n "s/^$1=//p" "$2" | tail -n1
    return 0
}

# Ecrit/modifie/retire (valeur vide) la cle $1 dans le fichier $2, sans
# toucher au reste -- l'admin peut avoir ajoute d'autres variables a la main
# (NFOGEN_ACCOUNTS_FILE, NFOGEN_CORS_ORIGINS...), ce fichier n'est jamais
# regenere en entier.
_set_env_var() {
    local key="$1" value="$2" file="$3"
    if [[ -z "${value}" ]]; then
        [[ -f "${file}" ]] && sed -i "/^${key}=/d" "${file}"
        return 0
    fi
    if [[ -f "${file}" ]] && grep -q "^${key}=" "${file}"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "${file}"
    else
        echo "${key}=${value}" >> "${file}"
    fi
}

# TLS optionnel, deux modes exclusifs (aucun des deux : HTTP nu, comme avant
# -- comportement par defaut inchange) :
#   NFOGEN_DOMAIN=mon-domaine.example   -> Caddy + Let's Encrypt automatique
#                                          (domaine public requis, DNS + port
#                                          80/443 joignables depuis Internet)
#   NFOGEN_LOCAL_TLS=1                  -> Caddy + certificat auto-signe
#                                          (aucun domaine/Internet requis,
#                                          adapte a un serveur local/LAN)
# Passe explicitement sur la ligne de commande cette execution : remplace le
# mode precedent. Sinon (cas typique de update.sh, qui ne repasse rien) : on
# reprend le mode deja persiste dans ${ENV_FILE} par une execution passee.
_CLI_DOMAIN="${NFOGEN_DOMAIN:-}"
_CLI_LOCAL_TLS="${NFOGEN_LOCAL_TLS:-}"
if [[ -n "${_CLI_DOMAIN}" || -n "${_CLI_LOCAL_TLS}" ]]; then
    NFOGEN_DOMAIN="${_CLI_DOMAIN}"
    NFOGEN_LOCAL_TLS="${_CLI_LOCAL_TLS}"
else
    NFOGEN_DOMAIN="$(_get_env_var NFOGEN_DOMAIN "${ENV_FILE}")"
    NFOGEN_LOCAL_TLS="$(_get_env_var NFOGEN_LOCAL_TLS "${ENV_FILE}")"
fi
if [[ -n "${NFOGEN_DOMAIN}" && -n "${NFOGEN_LOCAL_TLS}" ]]; then
    echo "NFOGEN_DOMAIN et NFOGEN_LOCAL_TLS sont mutuellement exclusifs (un seul mode TLS a la fois)." >&2
    exit 1
fi
if [[ -n "${NFOGEN_DOMAIN}" || -n "${NFOGEN_LOCAL_TLS}" ]]; then
    UVICORN_HOST="127.0.0.1"  # seul Caddy ecoute publiquement, cf. section TLS plus bas
else
    UVICORN_HOST="0.0.0.0"
fi

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

echo "==> Environnement Python (venv dedie + nfogen[api,gapscan])"
run_as_nfogen python3 -m venv "${INSTALL_DIR}/.venv"
run_as_nfogen "${INSTALL_DIR}/.venv/bin/pip" install --no-cache-dir --upgrade pip
# gapscan (httpx) : leger, installe par defaut -- GapScan reste inactif
# (501) tant que NFOGEN_C411_API_KEY n'est pas configuree (voir GAPSCAN.md).
run_as_nfogen "${INSTALL_DIR}/.venv/bin/pip" install --no-cache-dir "${INSTALL_DIR}[api,gapscan]"

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
# Ajoute uniquement si absent (jamais si deja present, meme avec une autre
# valeur) : contrairement a NFOGEN_DOMAIN/NFOGEN_LOCAL_TLS ci-dessous (mode
# explicitement choisi a chaque execution), GapScan doit garder la valeur
# de l'admin s'il l'a personnalisee -- fonctionne aussi bien sur une
# premiere installation qu'une mise a jour d'un ${ENV_FILE} deja existant.
if [[ -f "${ENV_FILE}" ]] && ! grep -q "^NFOGEN_GAPSCAN_CONFIG_FILE=" "${ENV_FILE}"; then
    echo "" >> "${ENV_FILE}"
    echo "# GapScan (voir GAPSCAN.md) : URLs/cles Sonarr/Radarr/C411 enregistrables" >> "${ENV_FILE}"
    echo "# a chaud depuis la page \"Scan C411\" (PUT /gapscan/config)." >> "${ENV_FILE}"
    echo "NFOGEN_GAPSCAN_CONFIG_FILE=${DATA_DIR}/gapscan_config.json" >> "${ENV_FILE}"
fi
_set_env_var NFOGEN_DOMAIN "${NFOGEN_DOMAIN}" "${ENV_FILE}"
_set_env_var NFOGEN_LOCAL_TLS "${NFOGEN_LOCAL_TLS}" "${ENV_FILE}"
if [[ -n "${NFOGEN_DOMAIN}" || -n "${NFOGEN_LOCAL_TLS}" ]]; then
    _set_env_var NFOGEN_COOKIE_SECURE "1" "${ENV_FILE}"
fi
chown "${SERVICE_USER}:${SERVICE_USER}" "${ENV_FILE}"
chmod 600 "${ENV_FILE}"

if [[ -n "${NFOGEN_DOMAIN}" || -n "${NFOGEN_LOCAL_TLS}" ]]; then
    echo "==> Reverse proxy TLS (Caddy)"
    if ! command -v caddy >/dev/null 2>&1; then
        echo "    Caddy absent : ajout du depot officiel (caddyserver.com/docs/install), puis installation"
        apt-get install -y --no-install-recommends debian-keyring debian-archive-keyring apt-transport-https
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
            | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
            > /etc/apt/sources.list.d/caddy-stable.list
        apt-get update
        apt-get install -y caddy
    fi

    # Ce script gere /etc/caddy/Caddyfile en entier (ecrase a chaque
    # execution, comme le service systemd de nfogen) : si Caddy sert deja
    # d'autres sites sur cette machine, ne pas utiliser NFOGEN_DOMAIN/
    # NFOGEN_LOCAL_TLS -- configurer le reverse proxy vers nfogen a la main.
    if [[ -n "${NFOGEN_DOMAIN}" ]]; then
        cat > /etc/caddy/Caddyfile <<EOF
# Genere par scripts/install.sh -- voir le commentaire dans le script avant
# d'editer a la main.
${NFOGEN_DOMAIN} {
    reverse_proxy 127.0.0.1:8000
}
EOF
        echo "    Domaine : ${NFOGEN_DOMAIN} -- certificat Let's Encrypt automatique"
        echo "    (necessite un enregistrement DNS deja en place et les ports 80/443 joignables depuis Internet)."
    else
        cat > /etc/caddy/Caddyfile <<EOF
# Genere par scripts/install.sh -- voir le commentaire dans le script avant
# d'editer a la main.
:443 {
    tls internal
    reverse_proxy 127.0.0.1:8000
}
EOF
        echo "    NFOGEN_LOCAL_TLS=1 -- certificat auto-signe (CA locale Caddy, aucune dependance a Internet)."
        echo "    A accepter/importer manuellement dans chaque navigateur client (avertissement attendu)."
    fi

    systemctl enable --now caddy
    systemctl reload caddy 2>/dev/null || systemctl restart caddy
fi

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
ExecStart=${INSTALL_DIR}/.venv/bin/uvicorn nfogen.api:app --host ${UVICORN_HOST} --port 8000
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
if [[ -n "${NFOGEN_DOMAIN}" ]]; then
    URL="https://${NFOGEN_DOMAIN}"
elif [[ -n "${NFOGEN_LOCAL_TLS}" ]]; then
    URL="https://${IP_ADDR:-<ip-serveur>} (certificat auto-signe, a accepter manuellement)"
else
    URL="http://${IP_ADDR:-<ip-serveur>}:8000"
fi
echo
echo "==> Installation/mise a jour terminee."
echo "    Statut  : systemctl status ${SERVICE_NAME}"
echo "    Logs    : journalctl -u ${SERVICE_NAME} -f"
echo "    URL     : ${URL}"
echo "    Config  : ${ENV_FILE} (token API...)"
echo "    Profils : ${PROFILES_DIR} (persistant, jamais touche par une mise a jour)"
echo "    Pour appliquer un changement de ${ENV_FILE} : systemctl restart ${SERVICE_NAME}"
echo "    Pour mettre a jour plus tard : sudo ./scripts/update.sh (depuis ${REPO_DIR})"
if [[ -z "${NFOGEN_DOMAIN}" && -z "${NFOGEN_LOCAL_TLS}" ]]; then
    echo "    TLS     : desactive -- trafic HTTP en clair, identifiants/cookie de session non chiffres."
    echo "              Pour l'activer, relancer avec :"
    echo "                sudo NFOGEN_DOMAIN=mon-domaine.example ./scripts/install.sh   (Let's Encrypt, domaine public)"
    echo "                sudo NFOGEN_LOCAL_TLS=1 ./scripts/install.sh                  (auto-signe, serveur local/LAN)"
fi
