#!/usr/bin/env bash
#
# Remove the bandcamp-plex systemd service, application files, and service user.
#
# Config (/etc/bandcamp-plex) and state (/var/lib/bandcamp-plex) are kept by
# default so cookies and sync history aren't lost. Pass --purge to remove them.
#
# Usage:  sudo ./uninstall.sh [--purge]

set -euo pipefail

PURGE=false
if [[ "${1:-}" == "--purge" ]]; then
    PURGE=true
fi

if [[ $EUID -ne 0 ]]; then
    echo "Error: this script must be run as root (sudo ./uninstall.sh)" >&2
    exit 1
fi

echo "==> Stopping and disabling service..."
systemctl stop bandcamp-plex 2>/dev/null || true
systemctl disable bandcamp-plex 2>/dev/null || true
rm -f /etc/systemd/system/bandcamp-plex.service
systemctl daemon-reload

echo "==> Removing application from /opt/bandcamp-plex..."
rm -rf /opt/bandcamp-plex

echo "==> Removing temp directory /var/tmp/bandcamp-plex..."
rm -rf /var/tmp/bandcamp-plex

if $PURGE; then
    echo "==> Purging config (/etc/bandcamp-plex) and state (/var/lib/bandcamp-plex)..."
    rm -rf /etc/bandcamp-plex
    rm -rf /var/lib/bandcamp-plex
else
    echo "==> Keeping config (/etc/bandcamp-plex) and state (/var/lib/bandcamp-plex)."
    echo "    Pass --purge to remove them."
fi

echo "==> Removing service user..."
userdel bandcamp-plex 2>/dev/null || true

echo "Done."
