# bandcamp-plex

A service that periodically checks your [Bandcamp](https://bandcamp.com)
fan collection against a Plex music library, downloads anything that's missing,
unzips it into the Plex music directory, and asks Plex to rescan.

Runs as a native systemd service — designed for a Raspberry Pi but works on any
Debian/Ubuntu-based Linux system.

---

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Quick start](#quick-start)
- [Getting your `cookies.txt`](#getting-your-cookiestxt)
- [Getting a Plex token](#getting-a-plex-token)
- [Configuration](#configuration)
- [Managing the service](#managing-the-service)
- [File layout on disk](#file-layout-on-disk)
- [How matching works](#how-matching-works)
- [Logs and troubleshooting](#logs-and-troubleshooting)
- [Updating](#updating)
- [Uninstalling](#uninstalling)
- [Development](#development)
- [FAQ](#faq)
- [Caveats](#caveats)

---

## How it works

On each sync iteration the service:

1. Loads your Bandcamp fan profile (`https://bandcamp.com/<username>`) using a
   browser-exported `cookies.txt` for authentication, and pages through the
   paginated `fancollection` API to enumerate every purchase.
2. Loads the list of albums already in your Plex music library. If
   `PLEX_URL` + `PLEX_TOKEN` are provided it queries Plex directly via the
   `plexapi` library; otherwise it falls back to scanning the music directory
   on disk.
3. For each purchase that isn't in Plex yet, it resolves a signed download URL
   for the preferred audio format (falling back through a list of formats if
   the preferred one isn't offered for that release).
4. Streams the zip (or single track file) to a scratch directory and extracts
   it safely into `MUSIC_DIR/<Artist>/<Album>/`.
5. Records the item's ID in a persistent state file so future runs skip it.
6. Once at least one new release has been installed, asks Plex to rescan the
   library section so the new music shows up in your clients.

The service then sleeps for `CHECK_INTERVAL` seconds and repeats. It handles
`SIGTERM`/`SIGINT` cleanly so `systemctl stop` won't corrupt an in-progress
download.

---

## Requirements

- **Raspberry Pi** (or any Debian/Ubuntu-based Linux machine) with Python 3.10+
  and `python3-venv` installed.
- A Bandcamp fan account with at least one purchase.
- A Plex Media Server with a Music library (optional — the service also
  works with a filesystem-only setup).
- Network access to `bandcamp.com` and your Plex server.

On Raspberry Pi OS (Bookworm), the dependencies are pre-installed. On older
versions you may need:

```bash
sudo apt update && sudo apt install python3 python3-venv python3-pip
```

---

## Quick start

```bash
git clone https://github.com/neil75/bandcamp-plex.git
cd bandcamp-plex

# 1. Run the install script (creates user, venv, systemd unit, directories).
sudo ./install.sh

# 2. Drop your Bandcamp cookies into the config directory.
sudo cp /path/to/exported/cookies.txt /etc/bandcamp-plex/cookies.txt
sudo chown bandcamp-plex:bandcamp-plex /etc/bandcamp-plex/cookies.txt

# 3. Edit the config — at minimum set BANDCAMP_USERNAME.
sudo nano /etc/bandcamp-plex/bandcamp-plex.conf

# 4. Make sure the music directory exists and is writable by the service.
#    Change the path to match MUSIC_DIR in your config.
sudo mkdir -p /srv/music
sudo chown bandcamp-plex:bandcamp-plex /srv/music

# 5. Start the service.
sudo systemctl start bandcamp-plex

# 6. Follow the logs.
journalctl -u bandcamp-plex -f
```

The first sync walks your entire Bandcamp collection, so expect it to take a
while on large libraries. Subsequent syncs only act on new purchases.

---

## Getting your `cookies.txt`

Bandcamp doesn't expose a public API for purchased items, so this service
authenticates by reusing your browser's session cookies. This repo includes
two helper scripts so you **don't need to install any browser extension**.

### Option A — Dev tools copy/paste (any browser)

This is the safest approach — no extensions, no file-system access, works in
Chrome, Edge, Firefox, or any browser with dev tools.

1. Log in to [bandcamp.com](https://bandcamp.com).
2. Press **F12** to open dev tools.
   - **Chrome / Edge:** go to the **Application** tab → **Cookies** →
     `https://bandcamp.com`.
   - **Firefox:** go to the **Storage** tab → **Cookies** →
     `https://bandcamp.com`.
3. Run the helper script (on your desktop, not the Pi):
   ```bash
   python3 extract-cookies.py
   ```
   It will prompt you for each cookie value — just copy/paste from the dev
   tools **Value** column. Only `identity` is required; the rest improve
   reliability.
4. Copy the resulting `cookies.txt` to the Pi:
   ```bash
   scp cookies.txt pi@<pi-address>:/tmp/
   # Then on the Pi:
   sudo cp /tmp/cookies.txt /etc/bandcamp-plex/cookies.txt
   sudo chown bandcamp-plex:bandcamp-plex /etc/bandcamp-plex/cookies.txt
   sudo chmod 600 /etc/bandcamp-plex/cookies.txt
   ```

### Option B — Firefox SQLite extraction (Linux / macOS)

If you use Firefox on a Linux or macOS desktop, you can extract cookies
directly from its profile database with zero manual copying:

```bash
# Requires sqlite3 — install with:  sudo apt install sqlite3
./extract-cookies-firefox.sh
```

The script auto-detects your Firefox profile, reads the `cookies.sqlite`
database (read-only copy), filters for Bandcamp cookies, and writes
`cookies.txt`. Then `scp` it to the Pi as in Option A step 4.

### Option C — Browser extension (if you prefer)

If you'd rather use an extension, any Netscape `cookies.txt` exporter works:
- [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) (Chrome/Edge)
- [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/) (Firefox)

Navigate to `bandcamp.com` and export cookies for that domain, then copy the
file to the Pi as in Option A step 4.

---

Cookies expire. If the service starts logging messages like *"cookies are
probably not for a logged-in session"*, repeat the export using whichever
method you prefer.

> **Security note:** `cookies.txt` gives full access to your Bandcamp account.
> Treat it like a password. The install script sets `/etc/bandcamp-plex` to be
> owned by and readable only by the `bandcamp-plex` service user.

---

## Getting a Plex token (optional)

A Plex token lets the service authenticate to Plex servers that require it.
**If your Plex server allows unauthenticated local access** (the default for
most home setups), you can skip the token entirely — just set `PLEX_URL` and
leave `PLEX_TOKEN` empty.

If you do need a token, the easiest ways to find it:

- **Via app.plex.tv:** open `app.plex.tv` in a browser, play any item, click
  `...` → **Get Info** → **View XML**. The URL will end with
  `?X-Plex-Token=xxxxxxxxxxxx`.
- **Via browser dev tools:** open your local Plex URL, press F12 → **Network**
  tab, click around in your library, and look for `X-Plex-Token` in the
  request URLs or headers.
- **From the Plex config on the server:** if Plex runs on the same machine:
  ```bash
  grep PlexOnlineToken "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Preferences.xml"
  ```

Plex integration is **entirely optional**. If you leave `PLEX_URL` unset, the
service falls back to scanning `MUSIC_DIR` on disk to decide what's already
there, and relies on Plex's own periodic scan to pick up new music.

---

## Configuration

All configuration lives in `/etc/bandcamp-plex/bandcamp-plex.conf`, which is a
standard systemd `EnvironmentFile` (one `KEY=value` per line). A commented
template is installed automatically by `install.sh` and is also available as
`.env.example` in this repo.

The only strictly required setting is `BANDCAMP_USERNAME`.

| Variable | Default | Description |
| --- | --- | --- |
| `BANDCAMP_USERNAME` | *(required)* | The username from `https://bandcamp.com/<username>` — the fan account to sync. |
| `BANDCAMP_COOKIES_FILE` | `/etc/bandcamp-plex/cookies.txt` | Path to the exported Netscape cookies file. |
| `BANDCAMP_FORMAT` | `flac` | Preferred audio format. Options: `flac`, `alac`, `wav`, `aiff-lossless`, `mp3-v0`, `mp3-320`, `vorbis`, `aac-hi`. Falls back through that list if the preferred format isn't offered for a given release. |
| `PLEX_URL` | *(unset)* | Base URL of your Plex server, e.g. `http://localhost:32400`. If unset, Plex integration is disabled. |
| `PLEX_TOKEN` | *(unset)* | Plex `X-Plex-Token`. Optional — only needed if your Plex server requires authentication for local connections. |
| `PLEX_LIBRARY` | `Music` | Name of the Plex library section to match against and rescan. |
| `MUSIC_DIR` | `/srv/music` | Where to install downloaded albums. Point this at the same directory Plex uses as its music library root. |
| `DOWNLOAD_DIR` | `/var/tmp/bandcamp-plex` | Scratch space for zip files before unpacking. Files are deleted after extraction. |
| `STATE_FILE` | `/var/lib/bandcamp-plex/state.json` | Persistent record of items already synced. |
| `CHECK_INTERVAL` | `3600` | Seconds between sync runs. Set to `0` to run exactly once and exit (useful with a cron job or `systemctl start --no-block`). |
| `DRY_RUN` | `false` | When true, logs which items would be downloaded but doesn't touch the library. Good for a first look. |

### Directories

| Path | Purpose | Created by |
| --- | --- | --- |
| `/etc/bandcamp-plex/` | Config (`bandcamp-plex.conf`) and credentials (`cookies.txt`). | `install.sh` |
| `/opt/bandcamp-plex/` | Application code and Python venv. | `install.sh` |
| `/var/lib/bandcamp-plex/` | Persistent state (`state.json`). | `install.sh` |
| `/var/tmp/bandcamp-plex/` | Scratch space for zip downloads. | `install.sh` |
| `/srv/music` (default) | Your Plex music library root. You must create this yourself if it doesn't exist. | You |

### Changing MUSIC_DIR

If your Plex music library lives somewhere other than `/srv/music` (e.g.
`/media/usb/music` on an external drive), update **two** places:

1. `MUSIC_DIR` in `/etc/bandcamp-plex/bandcamp-plex.conf`.
2. The `ReadWritePaths=` line in `/etc/systemd/system/bandcamp-plex.service` —
   replace `/srv/music` with your path. Then reload:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart bandcamp-plex
   ```

---

## Managing the service

```bash
# Start / stop / restart
sudo systemctl start bandcamp-plex
sudo systemctl stop bandcamp-plex
sudo systemctl restart bandcamp-plex

# Check status
systemctl status bandcamp-plex

# Follow live logs
journalctl -u bandcamp-plex -f

# See logs from the last sync
journalctl -u bandcamp-plex --since "1 hour ago"

# Run a one-shot dry-run sync (useful for testing)
sudo -u bandcamp-plex \
  BANDCAMP_USERNAME=yourname \
  BANDCAMP_COOKIES_FILE=/etc/bandcamp-plex/cookies.txt \
  MUSIC_DIR=/srv/music \
  STATE_FILE=/var/lib/bandcamp-plex/state.json \
  DOWNLOAD_DIR=/var/tmp/bandcamp-plex \
  CHECK_INTERVAL=0 \
  DRY_RUN=true \
  /opt/bandcamp-plex/venv/bin/python -m src

# Disable the service from starting at boot
sudo systemctl disable bandcamp-plex
```

---

## File layout on disk

After a successful sync, a newly purchased album lands at:

```
/srv/music/
└── <Artist>/
    └── <Album>/
        ├── 01 Track One.flac
        ├── 02 Track Two.flac
        └── cover.jpg
```

Filename characters that aren't safe on common filesystems (`<>:"/\|?*` and
control characters) are replaced with underscores. The rest of the zip's
internal structure is preserved as Bandcamp ships it.

A single-track purchase (rare, but possible) is placed directly inside an
album folder with the same name.

---

## How matching works

To decide whether an album is already in your library, both the Bandcamp item
and the Plex album are converted to a normalized form:

- lowercased
- accents stripped (`Björk` → `bjork`)
- a leading `the ` removed
- parenthetical suffixes like `(Deluxe Edition)` removed
- everything but `[a-z0-9]` stripped

The match is primarily on `(normalized_artist, normalized_album)`, with a
fallback to album-title-only so releases where Bandcamp's `band_name` and
Plex's `AlbumArtist` tag disagree still match.

Every purchase the service decides is already present is also recorded in
`state.json`, so on subsequent runs it short-circuits entirely without any
matching work.

---

## Logs and troubleshooting

```bash
journalctl -u bandcamp-plex -f
```

Common messages:

- **`Bandcamp profile loaded: fan_id=… X item(s) on first page, total=…`** —
  auth worked, enumeration is starting.
- **`Missing from Plex: <artist> - <album>`** — queued for download.
- **`Format flac unavailable for …; using mp3-320 instead`** — the release
  doesn't offer your preferred format; the next-best option was picked.
- **`Bandcamp profile blob had no fan_id`** — your cookies aren't logged in.
  Re-export `cookies.txt`.
- **`Bandcamp cookies file not found at /etc/bandcamp-plex/cookies.txt`** —
  the cookies file is missing. Export it from your browser and copy it over.
- **`Plex API query failed; falling back to filesystem scan`** — `PLEX_URL`
  or `PLEX_TOKEN` is wrong, or Plex is unreachable. The sync still runs using
  a filesystem scan as the source of truth.
- **`Failed to sync <artist> - <album>; will retry next run`** — download or
  extraction failed; the item stays unmarked and will be retried on the next
  iteration.

If something misbehaves, set `DRY_RUN=true` in the config, restart the
service, and check the logs to see what it *would* download without touching
your library.

---

## Updating

```bash
cd bandcamp-plex    # wherever you cloned the repo
git pull
sudo ./install.sh   # re-copies source + reinstalls deps
sudo systemctl restart bandcamp-plex
```

The install script does not overwrite your existing config in
`/etc/bandcamp-plex/bandcamp-plex.conf`, so your settings are preserved.

---

## Uninstalling

```bash
# Keeps config and state (cookies, state.json)
sudo ./uninstall.sh

# Or remove everything
sudo ./uninstall.sh --purge
```

---

## Development

The service is a small pure-Python project with three runtime dependencies:
`requests`, `beautifulsoup4`, and `plexapi`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run locally with env vars.
export BANDCAMP_USERNAME=yourname
export BANDCAMP_COOKIES_FILE=./cookies.txt
export MUSIC_DIR=./test-music
export DOWNLOAD_DIR=./test-downloads
export STATE_FILE=./test-state.json
export CHECK_INTERVAL=0
export DRY_RUN=true
python -m src
```

### Project layout

```
bandcamp-plex/
├── src/
│   ├── __init__.py
│   ├── __main__.py      # python -m src entry point
│   ├── main.py          # sync loop + signal handling
│   ├── config.py        # env → Config dataclass
│   ├── bandcamp.py      # fan collection scraper + download URL resolver
│   ├── plex_client.py   # plexapi + filesystem matchers, rescan trigger
│   ├── downloader.py    # streaming download, safe zip extraction
│   └── state.py         # JSON-backed set of synced item keys
├── bandcamp-plex.service       # systemd unit
├── install.sh                  # install/upgrade script
├── uninstall.sh                # removal script
├── extract-cookies.py          # build cookies.txt from dev-tools values
├── extract-cookies-firefox.sh  # extract cookies from Firefox SQLite DB
├── requirements.txt
├── .env.example                # config template
└── README.md
```

---

## FAQ

**Does this work without Plex?**
Yes. Leave `PLEX_URL` and `PLEX_TOKEN` unset and the service uses a
filesystem scan of `MUSIC_DIR` to decide what's already there. Plex's own
periodic scan will then pick up anything the service adds.

**Will this re-download my entire library every time?**
No. Items are recorded in `state.json` after the first successful sync (or
even after a match against Plex), so subsequent runs are near-instant for
everything that's already present.

**What if the preferred format isn't available for a release?**
The service walks a fallback list (`flac` → `alac` → `wav` →
`aiff-lossless` → `mp3-v0` → `mp3-320` → `vorbis` → `aac-hi`) and uses the
first one Bandcamp offers, logging a warning so you know it happened.

**Can I seed the state file manually?**
Yes. `state.json` is a plain JSON document of the form
`{"downloaded": ["album-123", "track-456", ...]}` where each entry is
`<item_type>-<bandcamp_item_id>`. Add keys by hand if you want the service to
skip them.

**How do I force a re-sync of a specific album?**
Delete the corresponding entry from `state.json` (or delete the whole file)
and also remove the album from the Plex library (or filesystem, if Plex is
disabled). The next sync iteration will re-download it.

**How often does it run?**
Every `CHECK_INTERVAL` seconds (default 1 hour). Set `CHECK_INTERVAL=0` to
run exactly once and exit — useful for cron-style scheduling.

**Can I store music on a USB drive?**
Absolutely. Set `MUSIC_DIR` in the config to the mount point of your drive
(e.g. `/media/usb/music`) and update the `ReadWritePaths=` line in the
systemd unit to match. Make sure the drive is mounted before the service
starts — you can add `RequiresMountsFor=/media/usb` to the `[Unit]` section
of the service file.

**Does it run at boot?**
Yes. The install script enables the service so it starts automatically.
Disable with `sudo systemctl disable bandcamp-plex`.

---

## Caveats

- **No official Bandcamp API.** This service scrapes the `pagedata` JSON blob
  embedded on the fan profile and download pages and calls the site's own
  `fancollection` endpoint. If Bandcamp changes either, the scraper will need
  updating. The parsing is defensive and logs keys on failure to make that
  easier.
- **Cookie-based auth.** There's no way around this today. Cookies expire;
  re-export when you see auth errors. Keep `cookies.txt` private.
- **One fan account at a time.** The service syncs a single
  `BANDCAMP_USERNAME`. Create multiple service instances (copy the unit file
  with a different name and point it at a separate config) if you need to sync
  more than one account.
- **Unique albums.** Matching is name-based, so two different albums with
  identical names will collide. This is rare in practice but worth knowing.
- **SD card wear.** On a Raspberry Pi with an SD card root filesystem, heavy
  downloading writes a lot of data. Consider pointing `DOWNLOAD_DIR` at a
  tmpfs or external drive to avoid wearing out the card. The state file is
  small and writes infrequently, so it's fine on the SD card.
- **Respect Bandcamp.** Only download things you actually own. This tool
  exists to make managing a legitimately-purchased collection easier, not to
  bypass any paywall.

---

## License

No license file is included; add one before publishing if you plan to share
the code.
