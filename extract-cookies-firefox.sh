#!/usr/bin/env bash
#
# Extract Bandcamp cookies directly from a Firefox profile's SQLite database.
# No browser extension required.
#
# Usage:
#   ./extract-cookies-firefox.sh                     # auto-detect profile
#   ./extract-cookies-firefox.sh /path/to/profile    # explicit profile dir
#   ./extract-cookies-firefox.sh -o /output/path     # custom output path
#
# Requirements: sqlite3 (sudo apt install sqlite3)
#
# The script reads Firefox's cookies.sqlite (read-only), extracts Bandcamp
# cookies, and writes a Netscape cookies.txt.

set -euo pipefail

OUTPUT="cookies.txt"
PROFILE_DIR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--output) OUTPUT="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [-o output.txt] [firefox-profile-dir]"
            exit 0
            ;;
        *) PROFILE_DIR="$1"; shift ;;
    esac
done

if ! command -v sqlite3 &>/dev/null; then
    echo "Error: sqlite3 is required.  Install with:  sudo apt install sqlite3" >&2
    exit 1
fi

# Auto-detect the default Firefox profile.
if [[ -z "$PROFILE_DIR" ]]; then
    FF_DIR=""
    for candidate in \
        "$HOME/.mozilla/firefox" \
        "$HOME/snap/firefox/common/.mozilla/firefox" \
        "$HOME/.var/app/org.mozilla.firefox/.mozilla/firefox"; do
        if [[ -d "$candidate" ]]; then
            FF_DIR="$candidate"
            break
        fi
    done
    if [[ -z "$FF_DIR" ]]; then
        echo "Error: could not find a Firefox profile directory." >&2
        echo "Pass the path explicitly:  $0 /path/to/profile" >&2
        exit 1
    fi
    # Pick the default-release profile, or fall back to any .default profile.
    PROFILE_DIR=$(find "$FF_DIR" -maxdepth 1 -type d -name '*.default-release' | head -1)
    if [[ -z "$PROFILE_DIR" ]]; then
        PROFILE_DIR=$(find "$FF_DIR" -maxdepth 1 -type d -name '*.default*' | head -1)
    fi
    if [[ -z "$PROFILE_DIR" ]]; then
        echo "Error: no default profile found under $FF_DIR" >&2
        exit 1
    fi
    echo "Using Firefox profile: $PROFILE_DIR"
fi

COOKIES_DB="$PROFILE_DIR/cookies.sqlite"
if [[ ! -f "$COOKIES_DB" ]]; then
    echo "Error: $COOKIES_DB not found." >&2
    exit 1
fi

# Firefox locks the database while running. Copy it so we can read safely.
TMP_DB=$(mktemp)
cp "$COOKIES_DB" "$TMP_DB"

{
    echo "# Netscape HTTP Cookie File"
    echo "# Extracted from Firefox profile by extract-cookies-firefox.sh"
    echo ""
    sqlite3 -separator $'\t' "$TMP_DB" \
        "SELECT host,
                CASE WHEN host LIKE '.%' THEN 'TRUE' ELSE 'FALSE' END,
                path,
                CASE WHEN isSecure THEN 'TRUE' ELSE 'FALSE' END,
                expiry,
                name,
                value
         FROM moz_cookies
         WHERE host LIKE '%bandcamp.com'
         ORDER BY name;"
} > "$OUTPUT"

rm -f "$TMP_DB"

COUNT=$(grep -c $'\t' "$OUTPUT" 2>/dev/null || echo 0)
echo "Wrote $COUNT cookie line(s) to $OUTPUT"

if [[ "$COUNT" -eq 0 ]]; then
    echo ""
    echo "Warning: no Bandcamp cookies found. Make sure you are logged in to"
    echo "bandcamp.com in Firefox and have visited the site recently."
    exit 1
fi

echo ""
echo "Next steps:"
echo "  1. Copy to the Pi:  scp $OUTPUT pi@<pi-address>:/tmp/"
echo "  2. Install it:"
echo "       sudo cp /tmp/cookies.txt /etc/bandcamp-plex/cookies.txt"
echo "       sudo chown bandcamp-plex:bandcamp-plex /etc/bandcamp-plex/cookies.txt"
echo "       sudo chmod 600 /etc/bandcamp-plex/cookies.txt"
echo "  3. Restart:  sudo systemctl restart bandcamp-plex"
