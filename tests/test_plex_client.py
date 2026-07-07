"""Tests for the Plex library matching logic."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.plex_client import PlexLibrary, normalize, tokenize, _fuzzy_match


class TestNormalize:
    def test_basic(self):
        assert normalize("Hello World") == "helloworld"

    def test_strips_leading_the(self):
        assert normalize("The Beatles") == "beatles"

    def test_strips_parenthesized(self):
        assert normalize("Album (Deluxe Edition)") == "album"

    def test_strips_bracketed(self):
        assert normalize("Album [Remastered]") == "album"

    def test_ampersand_to_and(self):
        assert normalize("Simon & Garfunkel") == normalize("Simon and Garfunkel")

    def test_edition_suffix_no_parens(self):
        assert normalize("Album Deluxe Edition") == "album"
        assert normalize("Album Remastered") == "album"
        assert normalize("Album - Deluxe Edition") == "album"

    def test_unicode(self):
        assert normalize("Bjork") == normalize("Björk")

    def test_empty(self):
        assert normalize("") == ""
        assert normalize(None) == ""


class TestFuzzyMatch:
    def test_exact(self):
        assert _fuzzy_match("Album", "Album")

    def test_edition_suffix(self):
        assert _fuzzy_match("Album", "Album (Deluxe Edition)")
        assert _fuzzy_match("Album", "Album Deluxe Edition")

    def test_substring(self):
        assert _fuzzy_match("Band Name", "Band Name feat. Someone")

    def test_word_overlap(self):
        assert _fuzzy_match("Lost in Translation", "Lost in Translation OST")

    def test_no_match(self):
        assert not _fuzzy_match("Completely Different", "Something Else")

    def test_empty(self):
        assert not _fuzzy_match("", "Something")
        assert not _fuzzy_match("Something", "")


class TestPlexLibrary:
    def _make_lib(self):
        lib = PlexLibrary()
        lib.add("Radiohead", "OK Computer")
        lib.add("Radiohead", "Kid A")
        lib.add("Simon & Garfunkel", "Bridge over Troubled Water")
        lib.add("Björk", "Homogenic")
        lib.add("The National", "Boxer")
        lib.add_track("Radiohead", "Paranoid Android")
        lib.add_track("Radiohead", "Everything in Its Right Place")
        lib.add_track("Simon & Garfunkel", "The Sound of Silence")
        return lib

    def test_exact_album_match(self):
        lib = self._make_lib()
        assert lib.contains_album("Radiohead", "OK Computer")

    def test_title_only_match(self):
        lib = self._make_lib()
        assert lib.contains_album("Different Artist", "OK Computer")

    def test_ampersand_vs_and(self):
        lib = self._make_lib()
        assert lib.contains_album(
            "Simon and Garfunkel", "Bridge over Troubled Water"
        )

    def test_edition_suffix_match(self):
        lib = self._make_lib()
        assert lib.contains_album("Radiohead", "OK Computer (Deluxe Edition)")
        assert lib.contains_album("Radiohead", "OK Computer Remastered")

    def test_fuzzy_artist_match(self):
        lib = self._make_lib()
        assert lib.contains_album(
            "Simon and Garfunkel", "Bridge over Troubled Water"
        )

    def test_fuzzy_artist_album_match(self):
        lib = self._make_lib()
        lib.add("Band Name", "Great Album")
        assert lib.contains_album("Band Name feat. Someone", "Great Album")

    def test_unicode_artist(self):
        lib = self._make_lib()
        assert lib.contains_album("Bjork", "Homogenic")

    def test_leading_the(self):
        lib = self._make_lib()
        assert lib.contains_album("National", "Boxer")

    def test_no_match(self):
        lib = self._make_lib()
        assert not lib.contains_album("Unknown Artist", "Unknown Album")

    def test_track_exact_match(self):
        lib = self._make_lib()
        assert lib.contains_track("Radiohead", "Paranoid Android")

    def test_track_fuzzy_artist(self):
        lib = self._make_lib()
        assert lib.contains_track(
            "Simon and Garfunkel", "The Sound of Silence"
        )

    def test_track_no_match(self):
        lib = self._make_lib()
        assert not lib.contains_track("Radiohead", "Nonexistent Track")

    def test_artist_tracks_matching(self):
        lib = self._make_lib()
        lib.add_track("Radiohead", "Paranoid Android")
        lib.add_track("Radiohead", "Subterranean Homesick Alien")
        lib.add_track("Radiohead", "Exit Music")
        assert lib.artist_has_tracks_matching(
            "Radiohead", "Paranoid Android / Exit Music"
        )

    def test_artist_tracks_matching_fuzzy_artist(self):
        lib = self._make_lib()
        lib.add_track("Simon & Garfunkel", "Mrs Robinson")
        lib.add_track("Simon & Garfunkel", "The Boxer")
        assert lib.artist_has_tracks_matching(
            "Simon and Garfunkel", "Mrs Robinson / The Boxer"
        )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
