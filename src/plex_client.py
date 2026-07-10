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
    text = text.replace("&", " and ")
    text = EDITION_SUFFIXES.sub("", text)
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
    if len(na) >= 4 and len(nb) >= 4 and (na in nb or nb in na):
        return True
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
    _artist_tracks: dict[str, set[str]] = field(
        default_factory=lambda: defaultdict(set)
    )
    _raw_artists: dict[str, str] = field(default_factory=dict)
    _fuzzy_artist_cache: dict[str, list[str]] = field(default_factory=dict)
    _has_track_data: bool = False

    def add(self, artist: str, title: str) -> None:
        a = normalize(artist)
        t = normalize(title)
        if not t:
            return
        self._exact.add((a, t))
        self._titles.add(t)
        self._artist_raw_albums[a].append(title)
        if a and a not in self._raw_artists:
            self._raw_artists[a] = artist

    def add_track(self, artist: str, track_title: str) -> None:
        a = normalize(artist)
        t = normalize(track_title)
        if a and t:
            self._artist_tracks[a].add(t)
            self._has_track_data = True
            if a not in self._raw_artists:
                self._raw_artists[a] = artist

    @property
    def album_count(self) -> int:
        return len(self._exact)

    @property
    def track_count(self) -> int:
        return sum(len(v) for v in self._artist_tracks.values())

    def _fuzzy_artist_keys(self, artist: str) -> list[str]:
        """Return normalized keys of Plex artists that fuzzy-match ``artist``."""
        a = normalize(artist)
        if a in self._fuzzy_artist_cache:
            return self._fuzzy_artist_cache[a]
        result = []
        for norm_a, raw_a in self._raw_artists.items():
            if norm_a != a and _fuzzy_match(artist, raw_a):
                result.append(norm_a)
        self._fuzzy_artist_cache[a] = result
        return result

    def _check_tracks_for_artist(self, norm_artist: str, norm_track: str) -> bool:
        tracks = self._artist_tracks.get(norm_artist, set())
        if not tracks:
            return False
        if norm_track in tracks:
            return True
        if len(norm_track) >= 4:
            for existing in tracks:
                if norm_track in existing or existing in norm_track:
                    return True
        return False

    def contains_album(self, artist: str, title: str) -> bool:
        a = normalize(artist)
        t = normalize(title)
        if not t:
            return False
        if (a, t) in self._exact:
            return True
        if t in self._titles:
            return True
        for raw_album in self._artist_raw_albums.get(a, []):
            if _fuzzy_match(title, raw_album):
                log.info(
                    "Fuzzy album match: Bandcamp '%s' ≈ Plex '%s' (artist: %s)",
                    title,
                    raw_album,
                    artist,
                )
                return True
        for fuzzy_a in self._fuzzy_artist_keys(artist):
            if (fuzzy_a, t) in self._exact:
                log.info(
                    "Fuzzy artist match: Bandcamp '%s' ≈ Plex '%s', album: '%s'",
                    artist,
                    self._raw_artists.get(fuzzy_a, fuzzy_a),
                    title,
                )
                return True
            for raw_album in self._artist_raw_albums.get(fuzzy_a, []):
                if _fuzzy_match(title, raw_album):
                    log.info(
                        "Fuzzy artist+album: Bandcamp '%s'≈'%s', '%s'≈'%s'",
                        artist,
                        self._raw_artists.get(fuzzy_a, fuzzy_a),
                        title,
                        raw_album,
                    )
                    return True
        return False

    def contains_track(self, artist: str, track_title: str) -> bool:
        """Check if an individual track exists in the library."""
        if not self._has_track_data:
            return False
        a = normalize(artist)
        t = normalize(track_title)
        if not t:
            return False
        if self._check_tracks_for_artist(a, t):
            return True
        for fuzzy_a in self._fuzzy_artist_keys(artist):
            if self._check_tracks_for_artist(fuzzy_a, t):
                log.info(
                    "Fuzzy artist track match: Bandcamp '%s' ≈ Plex '%s', track: '%s'",
                    artist,
                    self._raw_artists.get(fuzzy_a, fuzzy_a),
                    track_title,
                )
                return True
        return False

    def _tracks_overlap_title(self, tracks: set[str], album_title: str) -> bool:
        title_words = tokenize(album_title)
        if not title_words or len(title_words) < 2:
            return False
        matched = sum(1 for w in title_words if any(w in t for t in tracks))
        return matched / len(title_words) >= 0.7

    def artist_has_tracks_matching(self, artist: str, album_title: str) -> bool:
        """Check if an artist has tracks whose names overlap with an album title."""
        if not self._has_track_data:
            return False
        a = normalize(artist)
        tracks = self._artist_tracks.get(a, set())
        if tracks and self._tracks_overlap_title(tracks, album_title):
            return True
        for fuzzy_a in self._fuzzy_artist_keys(artist):
            tracks = self._artist_tracks.get(fuzzy_a, set())
            if tracks and self._tracks_overlap_title(tracks, album_title):
                log.info(
                    "Fuzzy artist track overlap: Bandcamp '%s' ≈ Plex '%s', album: '%s'",
                    artist,
                    self._raw_artists.get(fuzzy_a, fuzzy_a),
                    album_title,
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

    log.info("Loading albums from Plex...")
    for album in section.searchAlbums():
        lib.add(album.parentTitle or "", album.title or "")

    log.info("Loading tracks from Plex (this may take a moment)...")
    try:
        for track in section.searchTracks():
            artist = track.grandparentTitle or track.originalTitle or ""
            title = track.title or ""
            lib.add_track(artist, title)
            original = getattr(track, "originalTitle", None) or ""
            if original and original != artist:
                lib.add_track(original, title)
    except Exception:
        log.warning("Could not load tracks from Plex API; track-level matching disabled")

    log.info(
        "Loaded %d album(s) and %d track(s) from Plex library %r",
        lib.album_count,
        lib.track_count,
        library_name,
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
            for f in album_dir.iterdir():
                if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS:
                    lib.add_track(
                        artist_dir.name, _strip_track_number(f.name)
                    )
    log.info(
        "Loaded %d album(s) and %d track(s) from filesystem %s",
        lib.album_count,
        lib.track_count,
        music_dir,
    )
    return lib


def refresh_plex_library(url: str, token: str | None, library_name: str) -> None:
    from plexapi.server import PlexServer  # type: ignore

    server = PlexServer(url, token or "")
    section = server.library.section(library_name)
    section.update()
    log.info("Triggered Plex scan for library %r", library_name)
