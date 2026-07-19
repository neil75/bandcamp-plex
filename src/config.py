"""Runtime configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    bandcamp_username: str
    bandcamp_cookies_file: Path
    bandcamp_format: str
    plex_url: str | None
    plex_token: str | None
    plex_library: str
    music_dir: Path
    download_dir: Path
    state_file: Path
    check_interval: int
    dry_run: bool
    approval_mode: bool

    @classmethod
    def from_env(cls) -> "Config":
        def required(name: str) -> str:
            val = os.environ.get(name)
            if not val:
                raise RuntimeError(f"Missing required env var: {name}")
            return val

        return cls(
            bandcamp_username=required("BANDCAMP_USERNAME"),
            bandcamp_cookies_file=Path(
                os.environ.get(
                    "BANDCAMP_COOKIES_FILE",
                    "/etc/bandcamp-plex/cookies.txt",
                )
            ),
            bandcamp_format=os.environ.get("BANDCAMP_FORMAT", "flac"),
            plex_url=os.environ.get("PLEX_URL") or None,
            plex_token=os.environ.get("PLEX_TOKEN") or None,
            plex_library=os.environ.get("PLEX_LIBRARY", "Music"),
            music_dir=Path(os.environ.get("MUSIC_DIR", "/srv/music")),
            download_dir=Path(
                os.environ.get("DOWNLOAD_DIR", "/var/tmp/bandcamp-plex")
            ),
            state_file=Path(
                os.environ.get(
                    "STATE_FILE",
                    "/var/lib/bandcamp-plex/state.json",
                )
            ),
            check_interval=int(os.environ.get("CHECK_INTERVAL", "3600")),
            dry_run=_bool(os.environ.get("DRY_RUN")),
            approval_mode=_bool(os.environ.get("APPROVAL_MODE")),
        )
