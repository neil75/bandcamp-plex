"""Sync loop entry point."""
from __future__ import annotations

import logging
import signal
import sys
import time

from .bandcamp import BandcampClient
from .config import Config
from .downloader import download_file, install_album
from .plex_client import (
    PlexLibrary,
    load_from_filesystem,
    load_from_plex_api,
    normalize,
    refresh_plex_library,
    scan_artist_tracks,
    tokenize,
)
from .state import State

log = logging.getLogger("bandcamp-plex")


def build_plex_library(cfg: Config) -> PlexLibrary:
    if cfg.plex_url:
        try:
            return load_from_plex_api(cfg.plex_url, cfg.plex_token, cfg.plex_library)
        except Exception:
            log.exception(
                "Plex API query failed; falling back to filesystem scan of %s",
                cfg.music_dir,
            )
    return load_from_filesystem(cfg.music_dir)


def sync_once(cfg: Config, state: State) -> int:
    bc = BandcampClient(
        cfg.bandcamp_username,
        cfg.bandcamp_cookies_file,
        preferred_format=cfg.bandcamp_format,
    )
    plex = build_plex_library(cfg)
    cfg.download_dir.mkdir(parents=True, exist_ok=True)
    cfg.music_dir.mkdir(parents=True, exist_ok=True)

    # Cache artist track scans so we don't re-scan the same artist dir repeatedly.
    _artist_tracks_cache: dict[str, set[str]] = {}

    def _get_artist_tracks(artist: str) -> set[str]:
        a = normalize(artist)
        if a not in _artist_tracks_cache:
            _artist_tracks_cache[a] = scan_artist_tracks(cfg.music_dir, artist)
        return _artist_tracks_cache[a]

    def _track_file_exists(artist: str, track_title: str) -> bool:
        """Check if an individual track exists as a file under the artist."""
        tracks = _get_artist_tracks(artist)
        if not tracks:
            return False
        nt = normalize(track_title)
        if not nt:
            return False
        # Direct match: normalized track name matches a filename.
        if nt in tracks:
            return True
        # Substring match: track name appears within a filename or vice versa
        # (handles "Track Name" matching "01 Track Name" after stripping numbers,
        # or "Track Name (feat. X)" matching "Track Name").
        if len(nt) >= 4:
            for existing in tracks:
                if nt in existing or existing in nt:
                    return True
        return False

    def _album_tracks_present(artist: str, album_title: str) -> bool:
        """Check if an album's title words appear in existing track filenames."""
        tracks = _get_artist_tracks(artist)
        if not tracks:
            return False
        title_words = tokenize(album_title)
        if not title_words or len(title_words) < 2:
            return False
        matched = sum(1 for w in title_words if any(w in t for t in tracks))
        return matched / len(title_words) >= 0.7

    added = 0
    for item in bc.iter_collection():
        if state.has(item.key):
            continue

        is_track = item.item_type == "track"

        # For individual track purchases, check if the track file exists
        # under the artist's directory rather than matching album names.
        if is_track and plex.has_artist(item.artist):
            if _track_file_exists(item.artist, item.title):
                log.debug(
                    "Track already exists: %s - %s", item.artist, item.title
                )
                state.mark(item.key)
                continue

        # For albums (and tracks that didn't match above), try album-level matching.
        if plex.contains(item.artist, item.title):
            log.debug("Already in Plex: %s - %s", item.artist, item.title)
            state.mark(item.key)
            continue

        # Fallback: scan the artist dir for track-level evidence that the
        # content is already present under a different album name.
        if plex.has_artist(item.artist):
            if is_track:
                pass  # already tried above
            elif _album_tracks_present(item.artist, item.title):
                log.info(
                    "Track-level match: %s - %s (tracks found under artist dir)",
                    item.artist,
                    item.title,
                )
                state.mark(item.key)
                continue

        log.info(
            "Missing from Plex: %s - %s [%s]",
            item.artist,
            item.title,
            item.item_type,
        )
        if cfg.dry_run:
            continue

        try:
            url = bc.resolve_download_url(item)
            downloaded = download_file(bc.session, url, cfg.download_dir)
            install_album(downloaded, cfg.music_dir, item.artist, item.title)
            try:
                downloaded.unlink()
            except FileNotFoundError:
                pass
            state.mark(item.key)
            added += 1
        except Exception:
            log.exception(
                "Failed to sync %s - %s; will retry next run",
                item.artist,
                item.title,
            )

    if added and cfg.plex_url:
        try:
            refresh_plex_library(cfg.plex_url, cfg.plex_token, cfg.plex_library)
        except Exception:
            log.exception("Could not trigger Plex rescan")
    return added


class _StopFlag:
    def __init__(self) -> None:
        self.stop = False

    def __call__(self, *_args) -> None:  # signal handler
        self.stop = True
        log.info("Shutdown signal received; finishing current iteration")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = Config.from_env()
    state = State(cfg.state_file)

    stop = _StopFlag()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    log.info(
        "bandcamp-plex starting: user=%s format=%s interval=%ds music_dir=%s",
        cfg.bandcamp_username,
        cfg.bandcamp_format,
        cfg.check_interval,
        cfg.music_dir,
    )

    while not stop.stop:
        try:
            added = sync_once(cfg, state)
            log.info("Sync finished; %d new album(s) downloaded", added)
        except Exception:
            log.exception("Sync iteration failed")

        if cfg.check_interval <= 0:
            break

        for _ in range(cfg.check_interval):
            if stop.stop:
                break
            time.sleep(1)

    log.info("bandcamp-plex exiting")
    return 0


if __name__ == "__main__":
    sys.exit(main())
