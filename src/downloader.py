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
    """Unzip (or move) ``source`` into ``music_dir/Artist/Album``."""
    artist_dir = music_dir / safe_name(artist or "Unknown Artist")
    album_dir = artist_dir / safe_name(title or source.stem)
    album_dir.mkdir(parents=True, exist_ok=True)

    if zipfile.is_zipfile(source):
        _safe_extract(source, album_dir)
        log.info("Unzipped %s into %s", source.name, album_dir)
    else:
        target = album_dir / source.name
        shutil.move(str(source), str(target))
        log.info("Installed %s into %s", source.name, album_dir)
    return album_dir


def _safe_extract(zip_path: Path, album_dir: Path) -> None:
    album_root = album_dir.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (album_dir / member.filename).resolve()
            try:
                target.relative_to(album_root)
            except ValueError as exc:
                raise RuntimeError(
                    f"Refusing to extract unsafe zip entry {member.filename!r}"
                ) from exc
        zf.extractall(album_dir)
