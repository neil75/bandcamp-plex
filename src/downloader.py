"""Download purchases from Bandcamp and install them into the Plex music dir."""
from __future__ import annotations

import logging
import re
import shutil
import zipfile
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_INVALID_FS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(name: str) -> str:
    cleaned = _INVALID_FS_CHARS.sub("_", name).strip().strip(".")
    return cleaned or "unknown"


def download_file(session: requests.Session, url: str, dest_dir: Path) -> Path:
    """Stream ``url`` to ``dest_dir`` using the filename Bandcamp gives us."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    with session.get(url, stream=True, timeout=600) as resp:
        resp.raise_for_status()
        filename = _filename_from_response(resp, url)
        dest = dest_dir / safe_name(filename)
        tmp = dest.with_name(dest.name + ".part")
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                if chunk:
                    fh.write(chunk)
        tmp.replace(dest)
    log.info("Downloaded %s (%d bytes)", dest.name, dest.stat().st_size)
    return dest


def _filename_from_response(resp: requests.Response, url: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    if "filename=" in cd:
        raw = cd.split("filename=", 1)[1].strip()
        if raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
        raw = raw.split(";", 1)[0].strip()
        if raw:
            return raw
    tail = url.rsplit("/", 1)[-1].split("?", 1)[0]
    return tail or "download.bin"


def install_album(source: Path, music_dir: Path, artist: str, title: str) -> Path:
    """Unzip (or move) ``source`` into ``music_dir/Artist/Album``.

    Uses merge mode: existing files are kept, only new files are written.
    This lets pre-release tracks stay in place when the full album drops.
    """
    artist_dir = music_dir / safe_name(artist or "Unknown Artist")
    album_dir = artist_dir / safe_name(title or source.stem)
    album_dir.mkdir(parents=True, exist_ok=True)

    if zipfile.is_zipfile(source):
        _merge_extract(source, album_dir)
    else:
        target = album_dir / source.name
        if target.exists():
            log.info("Skipping existing file: %s", source.name)
        else:
            shutil.move(str(source), str(target))
            log.info("Installed %s into %s", source.name, album_dir)
    return album_dir


def _merge_extract(zip_path: Path, album_dir: Path) -> None:
    """Extract a ZIP into album_dir, skipping files that already exist."""
    album_root = album_dir.resolve()
    new_count = 0
    skip_count = 0
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            if member.is_dir():
                continue
            target = (album_dir / member.filename).resolve()
            try:
                target.relative_to(album_root)
            except ValueError as exc:
                raise RuntimeError(
                    f"Refusing to extract unsafe zip entry {member.filename!r}"
                ) from exc
            if target.exists():
                skip_count += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            zf.extract(member, album_dir)
            new_count += 1
    if skip_count:
        log.info(
            "Merged into %s: %d new file(s), %d existing file(s) kept",
            album_dir.name,
            new_count,
            skip_count,
        )
    else:
        log.info("Extracted %d file(s) into %s", new_count, album_dir)
