# bandcamp-plex

A small service that periodically checks your [Bandcamp](https://bandcamp.com)
fan collection against a Plex music library, downloads anything that's missing,
unzips it into the Plex music directory, and asks Plex to rescan.

Designed to run as a Docker container on an Unraid server (or anywhere Docker
runs).

---

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Quick start (Docker Compose)](#quick-start-docker-compose)
- [Unraid setup](#unraid-setup)
- [Getting your `cookies.txt`](#getting-your-cookiestxt)
- [Getting a Plex token](#getting-a-plex-token)
- [Configuration](#configuration)
- [File layout on disk](#file-layout-on-disk)
- [How matching works](#how-matching-works)
- [Logs and troubleshooting](#logs-and-troubleshooting)
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
`SIGTERM`/`SIGINT` cleanly so `docker stop` won't corrupt an in-progress
download.

---

## Requirements

- Docker (or Docker Compose). Tested with Docker 24+.
- A Bandcamp fan account with at least one purchase.
- A Plex Media Server with a Music library (optional — the service also
  works with a filesystem-only setup).
- Network access from the container to `bandcamp.com` and your Plex server.

---

## Quick start (Docker Compose)

```bash
git clone https://github.com/neil75/bandcamp-plex.git
cd bandcamp-plex

# 1. Create your config directory and drop your cookies.txt in it.
mkdir -p config downloads
cp /path/to/exported/cookies.txt config/cookies.txt

# 2. Edit docker-compose.yml to point /music at your Plex music share
#    and to set BANDCAMP_USERNAME / PLEX_URL / PLEX_TOKEN.
$EDITOR docker-compose.yml

# 3. Build and start the container.
docker compose up -d --build

# 4. Follow the logs to watch the first sync.
docker compose logs -f
```

The first sync walks your entire Bandcamp collection, so expect it to take a
while on large libraries. Subsequent syncs only act on new purchases.

---

## Unraid setup

The included `docker-compose.yml` is tuned for Unraid:

- Runs as `user: "99:100"` (the standard `nobody:users` owner of `/mnt/user`
  shares) so extracted files have the right ownership for Plex.
- Mounts `/mnt/user/music` as the target music directory. Change this to
  whatever path your Plex music library actually lives at on the array.

Steps:

1. Clone this repo to `/mnt/user/appdata/bandcamp-plex` (or wherever you keep
   compose stacks).
2. Create `config/cookies.txt` inside that directory — this is how the
   container authenticates to Bandcamp.
3. Edit `docker-compose.yml`:
   - `BANDCAMP_USERNAME` — your Bandcamp fan username.
   - `PLEX_URL` — usually `http://<unraid-ip>:32400`.
   - `PLEX_TOKEN` — see [below](#getting-a-plex-token).
   - `PLEX_LIBRARY` — the exact name of your Plex music library section
     (e.g. `"Music"`).
   - The `/music` volume — point it at your music share
     (`/mnt/user/music` by default).
4. `docker compose up -d --build`.

If you'd rather run it from the Unraid Docker UI instead of compose, create a
container using the image built from this Dockerfile and wire up the same
environment variables and volume mounts by hand.

---

## Getting your `cookies.txt`

Bandcamp doesn't expose a public API for purchased items, so this service
authenticates by reusing your browser's session cookies. Export them as a
standard Netscape `cookies.txt`:

1. Log in to [bandcamp.com](https://bandcamp.com) in a regular browser.
2. Install a cookies-exporter extension. Any of these work:
   - [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) (Chrome/Edge)
   - [cookies.txt](https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/) (Firefox)
3. Navigate to `bandcamp.com` and export cookies for that domain.
4. Save the file as `config/cookies.txt` inside the compose directory (the
   service mounts that directory to `/config` inside the container).

Cookies expire. If the service starts logging messages like *"cookies are
probably not for a logged-in session"*, repeat the export.

> **Security note:** `cookies.txt` gives full access to your Bandcamp account.
> Treat it like a password — don't commit it, share it, or put it in a public
> image. The `.gitignore` and `.dockerignore` already exclude the `config/`
> directory.

---

## Getting a Plex token

Plex's auth token is what lets the service query your library and trigger
rescans. Follow the official guide:

https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/

The short version: open any media item in the Plex web UI, click "Get Info" →
"View XML", and copy the `X-Plex-Token` query parameter from the resulting URL.

Plex integration is **optional**. If you leave `PLEX_URL` and `PLEX_TOKEN`
unset, the service falls back to scanning `MUSIC_DIR` on disk to decide what's
already there, and relies on Plex's own periodic scan to pick up new music.

---

## Configuration

All configuration is via environment variables. The only strictly required
one is `BANDCAMP_USERNAME` — everything else has sensible defaults baked into
the Docker image. A copy-pasteable template lives in `.env.example`.

| Variable | Default | Description |
| --- | --- | --- |
| `BANDCAMP_USERNAME` | *(required)* | The username from `https://bandcamp.com/<username>` — this is the fan account to sync. |
| `BANDCAMP_COOKIES_FILE` | `/config/cookies.txt` | Path inside the container to the exported Netscape cookies file. |
| `BANDCAMP_FORMAT` | `flac` | Preferred audio format. Options: `flac`, `alac`, `wav`, `aiff-lossless`, `mp3-v0`, `mp3-320`, `vorbis`, `aac-hi`. Falls back through that list if the preferred format isn't offered for a given release. |
| `PLEX_URL` | *(unset)* | Base URL of your Plex server, e.g. `http://plex:32400`. If unset, Plex integration is disabled. |
| `PLEX_TOKEN` | *(unset)* | Plex `X-Plex-Token`. Required when `PLEX_URL` is set. |
| `PLEX_LIBRARY` | `Music` | Name of the Plex library section to match against and rescan. |
| `MUSIC_DIR` | `/music` | Where to install downloaded albums. Mount your Plex music library here. |
| `DOWNLOAD_DIR` | `/downloads` | Scratch space for zip files before unpacking. Can be ephemeral. |
| `STATE_FILE` | `/config/state.json` | Persistent record of items already synced. Keep this alongside `cookies.txt`. |
| `CHECK_INTERVAL` | `3600` | Seconds between sync runs. Set to `0` to run exactly once and exit (useful for cron-driven setups). |
| `DRY_RUN` | `false` | When true, logs which items would be downloaded but doesn't touch the library. Good for a first look. |
| `TZ` | `Etc/UTC` | Timezone for log timestamps. |

### Volumes

| Mount | Purpose |
| --- | --- |
| `/config` | Holds `cookies.txt` and `state.json`. **Persist this.** |
| `/music` | Your Plex music library root. Albums are installed as `Artist/Album/`. |
| `/downloads` | Scratch space. Files are deleted after successful extraction; safe to make ephemeral. |

---

## File layout on disk

After a successful sync, a newly purchased album lands at:

```
/music/
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
docker compose logs -f bandcamp-plex
```

Common messages:

- **`Bandcamp profile loaded: fan_id=… X item(s) on first page, total=…`** —
  auth worked, enumeration is starting.
- **`Missing from Plex: <artist> - <album>`** — queued for download.
- **`Format flac unavailable for …; using mp3-320 instead`** — the release
  doesn't offer your preferred format; the next-best option was picked.
- **`Bandcamp profile blob had no fan_id`** — your cookies aren't logged in.
  Re-export `cookies.txt`.
- **`Bandcamp cookies file not found at /config/cookies.txt`** — check that
  the `config/` volume is mounted and contains `cookies.txt`.
- **`Plex API query failed; falling back to filesystem scan`** — `PLEX_URL`
  or `PLEX_TOKEN` is wrong, or Plex is unreachable. The sync still runs using
  a filesystem scan as the source of truth.
- **`Failed to sync <artist> - <album>; will retry next run`** — download or
  extraction failed; the item stays unmarked and will be retried on the next
  iteration.

If something misbehaves, set `DRY_RUN=true` and rerun — you'll see exactly
what the service thinks needs downloading without any writes to the library.

---

## Development

The service is a small pure-Python project with three runtime dependencies:
`requests`, `beautifulsoup4`, and `plexapi`.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run it directly (outside Docker). Requires the env vars above.
export BANDCAMP_USERNAME=yourname
export BANDCAMP_COOKIES_FILE=./config/cookies.txt
export MUSIC_DIR=./music
export DOWNLOAD_DIR=./downloads
export STATE_FILE=./config/state.json
export CHECK_INTERVAL=0
export DRY_RUN=true
python -m src
```

### Layout

```
src/
├── __init__.py
├── __main__.py      # `python -m src` entry point
├── main.py          # sync loop + signal handling
├── config.py        # env → Config dataclass
├── bandcamp.py      # fan collection scraper + download URL resolver
├── plex_client.py   # plexapi + filesystem matchers, rescan trigger
├── downloader.py    # streaming download, safe zip extraction
└── state.py         # JSON-backed set of synced item keys
```

### Building the image

```bash
docker build -t bandcamp-plex:dev .
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
everything that's already present. Mount `/config` on persistent storage to
keep that state across container restarts.

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
  `BANDCAMP_USERNAME`. Run multiple containers with different `/config`
  volumes if you need to sync more than one account.
- **Unique albums.** Matching is name-based, so two different albums with
  identical names will collide. This is rare in practice but worth knowing.
- **Respect Bandcamp.** Only download things you actually own. This tool
  exists to make managing a legitimately-purchased collection easier, not to
  bypass any paywall.

---

## License

No license file is included; add one before publishing if you plan to share
the image.
