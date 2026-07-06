"""Determine which albums already live in the Plex library."""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

EDITION_SUFFIXES = re.compile(
    r"\b("
    r"deluxe\s*edition|deluxe|special\s*edition|expanded\s*edition|"
    r"remastered\s*edition|remastered|remaster|anniversary\s*edition|"
    r"collector.?s?\s*edition|bonus\s*tracks?\s*edition|bonus\s*edition|"
    r"limited\s*edition|standard\s*edition|"
    r"bonus\s*tracks?|digital\s*only|digital\s*edition|"
    r"complete\s*edition|original\s*mix"
    r")\b",
    re.IGNORECASE,
)

STOP_WORDS = frozenset({
    "the", "a", "an", "of", "and", "in", "on", "at", "to", "for",
    "is", "it", "by", "or", "ep", "lp",
})


def normalize(text: str) -> str:
    """Aggressive normalization — strips to [a-z0-9] for exact matching."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"^the\s+", "", text)
    text = re.sub(r"[\[\(][^\]\)]*[\]\)]", "", text)
    text = re.sub(r"[^a-z0-9]+", "", text)
    return text


def tokenize(text: str) -> set[str]:
    """Extract significant words from a title for fuzzy comparison."""
    if not text:
        return set()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"^the\s+", "", text)
    text = EDITION_SUFFIXES.sub("", text)
    words = set(re.findall(r"[a-z0-9]+", text))
    words -= STOP_WORDS
    return words


def _fuzzy_match(a: str, b: str) -> bool:
    """Check if two album/artist names likely refer to the same release."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # One is a substring of the other (minimum 4 chars to avoid false positives).
    if len(na) >= 4 and len(nb) >= 4 and (na in nb or nb in na):
        return True
    # Significant-word overlap.
    wa, wb = tokenize(a), tokenize(b)
    if not wa or not wb:
        return False
    overlap = wa & wb
    smaller = min(len(wa), len(wb))
    if smaller > 0 and len(overlap) / smaller >= 0.7:
        return True
    return False


AUDIO_EXTENSIONS = frozenset({
    ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".wav", ".aiff", ".aif",
    ".wma", ".alac", ".ape", ".wv",
})

TRACK_NUM_PREFIX = re.compile(r"^\d{1,3}[\s._-]+")


def _strip_track_number(filename: str) -> str:
    stem = Path(filename).stem
    return TRACK_NUM_PREFIX.sub("", stem).strip()


@dataclass
class PlexLibrary:
    _exact: set[tuple[str, str]] = field(default_factory=set)
    _titles: set[str] = field(default_factory=set)
    _artist_raw_albums: dict[str, list[str]] = field(
        default_factory=lambda: defaultdict(list)
    )
    def add(self, artist: str, title: str) -> None:
        a = normalize(artist)
        t = normalize(title)
        if not t:
            return
        self._exact.add((a, t))
        self._titles.add(t)
        self._artist_raw_albums[a].append(title)

    @property
    def album_count(self) -> int:
        return len(self._exact)

    def contains(self, artist: str, title: str) -> bool:
        a = normalize(artist)
        t = normalize(title)
        if not t:
            return False
        # 1. Exact normalized match.
        if (a, t) in self._exact:
            return True
        # 2. Title-only exact match (handles artist name differences).
        if t in self._titles:
            return True
        # 3. Fuzzy album name match within the same artist.
        for raw_album in self._artist_raw_albums.get(a, []):
            if _fuzzy_match(title, raw_album):
                log.info(
                    "Fuzzy match: Bandcamp '%s' ≈ Plex '%s' (artist: %s)",
                    title,
                    raw_album,
                    artist,
                )
                return True
        return False

    def has_artist(self, artist: str) -> bool:
        return normalize(artist) in self._artist_raw_albums


def load_from_plex_api(url: str, token: str | None, library_name: str) -> PlexLibrary:
    from plexapi.server import PlexServer  # type: ignore

    server = PlexServer(url, token or "")
    section = server.library.section(library_name)
    lib = PlexLibrary()
    for album in section.searchAlbums():
        lib.add(album.parentTitle or "", album.title or "")
    log.info(
        "Loaded %d album(s) from Plex library %r", lib.album_count, library_name
    )
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
    log.info(
        "Loaded %d album(s) from filesystem %s", lib.album_count, music_dir
    )
    return lib


def scan_artist_tracks(music_dir: Path, artist: str) -> set[str]:
    """Scan audio filenames under a single artist dir (on-demand, not at startup)."""
    a_dir = music_dir / artist
    if not a_dir.is_dir():
        for candidate in music_dir.iterdir():
            if candidate.is_dir() and normalize(candidate.name) == normalize(artist):
                a_dir = candidate
                break
        else:
            return set()
    tracks: set[str] = set()
    for album_dir in a_dir.iterdir():
        if not album_dir.is_dir():
            continue
        for f in album_dir.iterdir():
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS:
                tracks.add(normalize(_strip_track_number(f.name)))
    return tracks


def refresh_plex_library(url: str, token: str | None, library_name: str) -> None:
    from plexapi.server import PlexServer  # type: ignore

    server = PlexServer(url, token or "")
    section = server.library.section(library_name)
    section.update()
    log.info("Triggered Plex scan for library %r", library_name)
