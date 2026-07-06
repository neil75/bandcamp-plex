"""Bandcamp fan collection client.

Bandcamp does not publish an API for purchased items, so this module uses
session cookies (exported from a logged-in browser as a Netscape cookies.txt)
to scrape the fan profile page and call the paginated ``fancollection`` API
that the site uses itself. For each purchase it resolves a signed download URL
for the preferred audio format.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Iterable, Iterator

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

COLLECTION_API = "https://bandcamp.com/api/fancollection/1/collection_items"
PAGE_SIZE = 100

# Preference order when the user's preferred format isn't offered for a release.
FALLBACK_FORMATS = (
    "flac",
    "alac",
    "wav",
    "aiff-lossless",
    "mp3-v0",
    "mp3-320",
    "vorbis",
    "aac-hi",
)


@dataclass(frozen=True)
class CollectionItem:
    sale_item_id: str
    sale_item_type: str
    item_id: int
    item_type: str  # "album" or "track"
    artist: str
    title: str
    download_page_url: str

    @property
    def key(self) -> str:
        """Stable identifier used for the local state file."""
        return f"{self.item_type}-{self.item_id}"


class BandcampClient:
    def __init__(
        self,
        username: str,
        cookies_file: Path,
        preferred_format: str = "flac",
    ) -> None:
        self.username = username
        self.preferred_format = preferred_format
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/html, */*",
            }
        )
        if not cookies_file.exists():
            raise RuntimeError(
                f"Bandcamp cookies file not found at {cookies_file}. "
                "Export cookies.txt from a logged-in browser session."
            )
        jar = MozillaCookieJar(str(cookies_file))
        jar.load(ignore_discard=True, ignore_expires=True)
        self.session.cookies = jar

    # ------------------------------------------------------------------ collection

    def iter_collection(self) -> Iterator[CollectionItem]:
        """Yield every item the fan has purchased, oldest pagination last."""
        fan_id, initial_items, next_token = self._load_profile()
        seen: set[str] = set()
        for item in initial_items:
            if item.key in seen:
                continue
            seen.add(item.key)
            yield item

        token = next_token
        empty_streak = 0
        while token:
            payload = self._fetch_page(fan_id, token)
            items = list(self._items_from_payload(payload))
            if not items:
                empty_streak += 1
                if empty_streak >= 2:
                    break
            else:
                empty_streak = 0
            for item in items:
                if item.key in seen:
                    continue
                seen.add(item.key)
                yield item
            if not payload.get("more_available"):
                break
            new_token = payload.get("last_token")
            if not new_token or new_token == token:
                break
            token = new_token

    def _fetch_page(self, fan_id: int, token: str) -> dict:
        resp = self.session.post(
            COLLECTION_API,
            json={"fan_id": fan_id, "older_than_token": token, "count": PAGE_SIZE},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def _load_profile(self) -> tuple[int, list[CollectionItem], str | None]:
        url = f"https://bandcamp.com/{self.username}"
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        blob = _extract_pagedata(resp.text)
        if blob is None:
            raise RuntimeError(
                "Could not find pagedata on Bandcamp profile page. "
                "The cookies file may be expired or the username wrong."
            )
        fan_data = blob.get("fan_data") or {}
        fan_id = fan_data.get("fan_id")
        if not fan_id:
            raise RuntimeError(
                "Bandcamp profile blob had no fan_id - cookies are probably "
                "not for a logged-in session."
            )
        collection_data = blob.get("collection_data") or {}
        redownload_urls = collection_data.get("redownload_urls") or {}
        item_cache = ((blob.get("item_cache") or {}).get("collection")) or {}
        items = list(_items_from_cache(item_cache.values(), redownload_urls))
        item_count = collection_data.get("item_count", "?")
        last_token = collection_data.get("last_token")
        log.info(
            "Bandcamp profile loaded: fan_id=%s, %d item(s) on first page, "
            "total=%s",
            fan_id,
            len(items),
            item_count,
        )
        if not items:
            log.debug(
                "Profile blob keys: %s; collection_data keys: %s; "
                "item_cache size: %d; redownload_urls size: %d",
                sorted(blob.keys()),
                sorted(collection_data.keys()),
                len(item_cache),
                len(redownload_urls),
            )
        # Even when the profile page has 0 cached items (Bandcamp sometimes
        # returns an empty initial batch), we can still paginate if there's a
        # token or if we know items exist.
        if not last_token and not items and item_count and item_count != "?":
            # No token from initial page — seed with a very large timestamp so
            # the API returns the newest items first.
            last_token = "9999999999::a::"
            log.info(
                "No last_token on profile page; seeding pagination to fetch "
                "%s item(s) via API",
                item_count,
            )
        return int(fan_id), items, last_token

    @staticmethod
    def _items_from_payload(payload: dict) -> Iterator[CollectionItem]:
        redownload_urls = payload.get("redownload_urls") or {}
        for raw in payload.get("items") or []:
            item = _build_item(raw, redownload_urls)
            if item is not None:
                yield item

    # -------------------------------------------------------------------- downloads

    def resolve_download_url(self, item: CollectionItem) -> str:
        """Return a direct download URL for ``item`` in the preferred format."""
        resp = self.session.get(item.download_page_url, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        blob = _extract_pagedata(resp.text)
        if blob is None:
            raise RuntimeError(
                f"Download page for {item.key} did not contain a pagedata blob"
            )
        download_items = blob.get("download_items") or blob.get("digital_items") or []
        if not download_items:
            raise RuntimeError(f"No download_items for {item.key}")
        # Bandcamp's download page is always keyed to a single purchase; take the
        # first entry but if multiple are present prefer one matching item_id.
        entry = download_items[0]
        for candidate in download_items:
            if str(candidate.get("item_id")) == str(item.item_id):
                entry = candidate
                break
        downloads = entry.get("downloads") or {}
        fmt = downloads.get(self.preferred_format)
        if fmt is None:
            for name in FALLBACK_FORMATS:
                if name in downloads:
                    log.warning(
                        "Format %s unavailable for %s - %s; using %s instead",
                        self.preferred_format,
                        item.artist,
                        item.title,
                        name,
                    )
                    fmt = downloads[name]
                    break
        if fmt is None or not fmt.get("url"):
            available = sorted(downloads.keys())
            raise RuntimeError(
                f"No usable download format for {item.key} "
                f"(available: {available})"
            )
        return fmt["url"]


# ---------------------------------------------------------------------- helpers


def _extract_pagedata(html: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.find(id="pagedata")
    if node is None:
        return None
    raw = node.get("data-blob")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.exception("Could not JSON-decode pagedata blob")
        return None


def _items_from_cache(
    raws: Iterable[dict], redownload_urls: dict
) -> Iterator[CollectionItem]:
    for raw in raws:
        item = _build_item(raw, redownload_urls)
        if item is not None:
            yield item


def _build_item(raw: dict, redownload_urls: dict) -> CollectionItem | None:
    sale_item_id = raw.get("sale_item_id")
    sale_item_type = raw.get("sale_item_type") or "p"
    item_id = raw.get("item_id")
    item_type = raw.get("item_type") or "album"
    if sale_item_id is None or item_id is None:
        return None
    key = f"{sale_item_type}{sale_item_id}"
    download_url = redownload_urls.get(key)
    if not download_url:
        # Some collection entries (e.g. free streams) have no redownload link.
        return None
    return CollectionItem(
        sale_item_id=str(sale_item_id),
        sale_item_type=str(sale_item_type),
        item_id=int(item_id),
        item_type=str(item_type),
        artist=(raw.get("band_name") or "").strip(),
        title=(raw.get("item_title") or "").strip(),
        download_page_url=str(download_url),
    )
