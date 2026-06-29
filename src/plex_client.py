"""Determine which albums already live in the Plex library."""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


def normalize(text: str) -> str:
    """Fold an artist/album name so loose comparisons still match."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"^the\s+", "", text)
    text = re.sub(r"[\[\(][^\]\)]*[\]\)]", "", text)  # drop parentheticals
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


@dataclass
class PlexLibrary:
    albums: set[tuple[str, str]] = field(default_factory=set)
    album_titles: set[str] = field(default_factory=set)

    def add(self, artist: str, title: str) -> None:
        a = normalize(artist)
        t = normalize(title)
        if not t:
            return
        self.albums.add((a, t))
        self.album_titles.add(t)

    def contains(self, artist: str, title: str) -> bool:
        a = normalize(artist)
        t = normalize(title)
        if not t:
            return False
        if (a, t) in self.albums:
            return True
        # Fallback: title-only match (handles artist name mismatches between
        # Bandcamp's band_name and Plex's AlbumArtist tag).
        return t in self.album_titles


def load_from_plex_api(url: str, token: str | None, library_name: str) -> PlexLibrary:
    from plexapi.server import PlexServer  # type: ignore

    server = PlexServer(url, token or "")
    section = server.library.section(library_name)
    lib = PlexLibrary()
    for album in section.searchAlbums():
        lib.add(album.parentTitle or "", album.title or "")
    log.info("Loaded %d album(s) from Plex library %r", len(lib.albums), library_name)
    return lib


def load_from_filesystem(music_dir: Path) -> PlexLibrary:
    lib = PlexLibrary()
    if not music_dir.exists():
        log.warning("Music dir %s does not exist; treating library as empty", music_dir)
        return lib
    for artist_dir in music_dir.iterdir():
        if not artist_dir.is_dir() or artist_dir.name.startswith("."):
            continue
        for album_dir in artist_dir.iterdir():
            if not album_dir.is_dir() or album_dir.name.startswith("."):
                continue
            lib.add(artist_dir.name, album_dir.name)
    log.info("Loaded %d album(s) from filesystem %s", len(lib.albums), music_dir)
    return lib


def refresh_plex_library(url: str, token: str | None, library_name: str) -> None:
    from plexapi.server import PlexServer  # type: ignore

    server = PlexServer(url, token or "")
    section = server.library.section(library_name)
    section.update()
    log.info("Triggered Plex scan for library %r", library_name)
