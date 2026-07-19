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
    refresh_plex_library,
)
from .review import (
    PendingItem,
    clear_decisions,
    generate_review_html,
    load_decisions,
    write_pending,
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


def _find_missing(cfg: Config, state: State, bc: BandcampClient, plex: PlexLibrary):
    """Yield (CollectionItem, is_track) tuples for items missing from Plex."""
    for item in bc.iter_collection():
        if state.has(item.key):
            continue

        is_track = item.item_type == "track"

        if is_track:
            if plex.contains_track(item.artist, item.title):
                log.debug(
                    "Track found in Plex: %s - %s", item.artist, item.title
                )
                state.mark(item.key)
                continue

        if plex.contains_album(item.artist, item.title):
            log.debug("Album found in Plex: %s - %s", item.artist, item.title)
            state.mark(item.key)
            continue

        if not is_track and plex.artist_has_tracks_matching(
            item.artist, item.title
        ):
            log.info(
                "Track-level match: %s - %s (tracks found under artist)",
                item.artist,
                item.title,
            )
            state.mark(item.key)
            continue

        yield item


def _download_item(cfg: Config, state: State, bc: BandcampClient, item) -> bool:
    try:
        url = bc.resolve_download_url(item)
        downloaded = download_file(bc.session, url, cfg.download_dir)
        install_album(downloaded, cfg.music_dir, item.artist, item.title)
        try:
            downloaded.unlink()
        except FileNotFoundError:
            pass
        state.mark(item.key)
        return True
    except Exception:
        log.exception(
            "Failed to sync %s - %s; will retry next run",
            item.artist,
            item.title,
        )
        return False


def _process_decisions(cfg: Config, state: State, bc: BandcampClient) -> int:
    """Process a decisions.json file: download approved, mark skipped."""
    decisions_file = cfg.state_file.parent / "decisions.json"
    decisions = load_decisions(decisions_file)
    if decisions is None:
        return 0

    for key in decisions.get("skip", []):
        state.mark(key)
    skipped = len(decisions.get("skip", []))
    if skipped:
        log.info("Marked %d item(s) as skipped per user decision", skipped)

    to_download = set(decisions.get("download", []))
    if not to_download:
        clear_decisions(decisions_file)
        return 0

    log.info("Processing %d approved download(s)...", len(to_download))
    added = 0
    for item in bc.iter_collection():
        if item.key not in to_download:
            continue
        if state.has(item.key):
            continue
        log.info("Downloading approved: %s - %s", item.artist, item.title)
        if _download_item(cfg, state, bc, item):
            added += 1

    clear_decisions(decisions_file)
    return added


def sync_once(cfg: Config, state: State) -> int:
    bc = BandcampClient(
        cfg.bandcamp_username,
        cfg.bandcamp_cookies_file,
        preferred_format=cfg.bandcamp_format,
    )
    plex = build_plex_library(cfg)
    cfg.download_dir.mkdir(parents=True, exist_ok=True)
    cfg.music_dir.mkdir(parents=True, exist_ok=True)

    added = 0

    if cfg.approval_mode:
        added = _process_decisions(cfg, state, bc)

    pending = []
    for item in _find_missing(cfg, state, bc, plex):
        log.info(
            "Missing from Plex: %s - %s [%s]",
            item.artist,
            item.title,
            item.item_type,
        )

        if cfg.approval_mode:
            pending.append(PendingItem(
                key=item.key,
                artist=item.artist,
                title=item.title,
                item_type=item.item_type,
            ))
        elif not cfg.dry_run:
            if _download_item(cfg, state, bc, item):
                added += 1

    if cfg.approval_mode and pending:
        review_dir = cfg.state_file.parent
        write_pending(pending, review_dir / "pending.json")
        generate_review_html(pending, review_dir / "review.html")
        log.info(
            "%d item(s) awaiting approval. Review at: %s",
            len(pending),
            review_dir / "review.html",
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
