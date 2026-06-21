#!/usr/bin/env bash
#
# Install bandcamp-plex as a systemd service on a Raspberry Pi (or any
# Debian/Ubuntu-based Linux system).
#
# Usage:  sudo ./install.sh
#
# What it does:
#   1. Creates a bandcamp-plex system user (no login shell, no home dir).
#   2. Copies the application to /opt/bandcamp-plex.
#   3. Creates a Python virtual environment and installs dependencies.
#   4. Creates config/state directories with appropriate ownership.
#   5. Installs the systemd unit and enables (but does not start) the service.
#
# After running this script you still need to:
#   - Place your cookies.txt at /etc/bandcamp-plex/cookies.txt
#   - Edit /etc/bandcamp-plex/bandcamp-plex.conf (at minimum set BANDCAMP_USERNAME)
#   - sudo systemctl start bandcamp-plex

set -euo pipefail

INSTALL_DIR="/opt/bandcamp-plex"
CONF_DIR="/etc/bandcamp-plex"
STATE_DIR="/var/lib/bandcamp-plex"
TMP_DIR="/var/tmp/bandcamp-plex"
SERVICE_USER="bandcamp-plex"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "Error: this script must be run as root (sudo ./install.sh)" >&2
    exit 1
fi

echo "==> Creating service user '${SERVICE_USER}'..."
if ! id -u "${SERVICE_USER}" &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "${SERVICE_USER}"
fi

echo "==> Installing application to ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}"
cp -r "${SCRIPT_DIR}/src" "${INSTALL_DIR}/src"
cp "${SCRIPT_DIR}/requirements.txt" "${INSTALL_DIR}/requirements.txt"

echo "==> Creating Python virtual environment..."
python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --upgrade pip >/dev/null
"${INSTALL_DIR}/venv/bin/pip" install -r "${INSTALL_DIR}/requirements.txt"

echo "==> Creating config directory ${CONF_DIR}..."
mkdir -p "${CONF_DIR}"
if [[ ! -f "${CONF_DIR}/bandcamp-plex.conf" ]]; then
    cp "${SCRIPT_DIR}/.env.example" "${CONF_DIR}/bandcamp-plex.conf"
    echo "    Installed default config at ${CONF_DIR}/bandcamp-plex.conf — edit before starting."
else
    echo "    Config already exists; not overwriting."
fi
chmod 600 "${CONF_DIR}/bandcamp-plex.conf"
chown -R "${SERVICE_USER}:${SERVICE_USER}" "${CONF_DIR}"

echo "==> Creating state directory ${STATE_DIR}..."
mkdir -p "${STATE_DIR}"
chown "${SERVICE_USER}:${SERVICE_USER}" "${STATE_DIR}"

echo "==> Creating temp download directory ${TMP_DIR}..."
mkdir -p "${TMP_DIR}"
chown "${SERVICE_USER}:${SERVICE_USER}" "${TMP_DIR}"

echo "==> Installing systemd unit..."
cp "${SCRIPT_DIR}/bandcamp-plex.service" /etc/systemd/system/bandcamp-plex.service
systemctl daemon-reload
systemctl enable bandcamp-plex

chown -R "${SERVICE_USER}:${SERVICE_USER}" "${INSTALL_DIR}"

echo ""
echo "Installation complete. Next steps:"
echo ""
echo "  1. Place your Bandcamp cookies.txt at:"
echo "       ${CONF_DIR}/cookies.txt"
echo ""
echo "  2. Edit the config file:"
echo "       sudo nano ${CONF_DIR}/bandcamp-plex.conf"
echo "     At minimum set BANDCAMP_USERNAME."
echo ""
echo "  3. Make sure the music directory exists and is writable:"
echo "       sudo mkdir -p /srv/music"
echo "       sudo chown ${SERVICE_USER}:${SERVICE_USER} /srv/music"
echo "     (Or change MUSIC_DIR in the config and update ReadWritePaths"
echo "      in /etc/systemd/system/bandcamp-plex.service to match.)"
echo ""
echo "  4. Start the service:"
echo "       sudo systemctl start bandcamp-plex"
echo ""
echo "  5. Follow the logs:"
echo "       journalctl -u bandcamp-plex -f"
