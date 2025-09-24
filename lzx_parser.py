"""Utilities for fetching, normalizing, grouping and exporting LZX RSS offers.

Main capabilities:
- Fetch recent RSS entries (time–window based).
- Normalize and optionally de-duplicate offers using title, price and image similarity.
- Resolve redirect links concurrently.
- Download images and compute perceptual hashes to detect near-duplicates.
- Export grouped offers into lightweight dict structures.
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Sequence

import feedparser
import imagehash
import requests
from PIL import Image, UnidentifiedImageError
from babel.dates import format_date
from dateutil.parser import parse
from feedparser import FeedParserDict
from pytz import timezone

# -----------------------------------------------------------------------------
# Configuration & Logging
# -----------------------------------------------------------------------------
DEFAULT_TZ = 'Europe/Warsaw'
DEFAULT_LOCALE = 'pl_PL'
IMAGE_HASH_SIZE = 16
IMAGE_SIMILARITY_THRESHOLD = 0.10  # proportion of differing bits (lower = more similar)
DEFAULT_THREADS = 8
REQUEST_TIMEOUT = 5  # seconds

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='[%(levelname)s] %(asctime)s %(name)s: %(message)s'
    )


# -----------------------------------------------------------------------------
# Data Structures
# -----------------------------------------------------------------------------
@dataclass
class LzxEntry:
    """Wrapper around a feedparser entry with cached derived data.

    Attributes:
        raw: Original FeedParserDict entry.
        link: Resolved (possibly de-redirected) URL of the offer.
        title: Raw title string.
        published: Published date string as provided by the feed.
        summary: Typically contains price or short description.
        href: Image URL (may be missing).
        normalized_title: Title stripped to alphanumerics (lowercase) for comparisons.
        image: PIL Image object if downloaded.
        image_hash: Perceptual hash (average hash) for similarity grouping.
    """
    raw: FeedParserDict
    link: str
    title: str
    published: str
    summary: str
    href: str | None = None
    normalized_title: str = field(init=False)
    image: Image.Image | None = None
    image_hash: imagehash.ImageHash | None = None

    def __post_init__(self) -> None:
        """Compute and cache a normalized version of the title for grouping."""
        # Inline normalization (removed global remove_special_characters)
        self.normalized_title = self._normalize_title(self.title)

    @staticmethod
    def _normalize_title(value: str) -> str:
        """Return lowercase alphanumeric-only variant of a title string."""
        return re.sub(r'[^a-zA-Z0-9]', '', value).lower()

    @property
    def published_dt(self) -> datetime:
        """Parsed datetime object of the published field."""
        return parse(self.published)


class LzxScrapper:
    """Class interface making LZX handling consistent with other scrappers.

    Typical usage:
        scrapper = LzxScrapper(rss_url)
        entries = scrapper.get_offers()
        unique = scrapper.get_unique(entries)
        duplicates = scrapper.get_duplicates(entries)
    """

    def __init__(
            self,
            rss_url: str,
            *,
            hours: int = 24,
            grace_minutes: int = 10,
            tz_name: str = DEFAULT_TZ,
            threads: int = DEFAULT_THREADS
    ) -> None:
        self.rss_url = rss_url
        self.hours = hours
        self.grace_minutes = grace_minutes
        self.tz_name = tz_name
        self.threads = threads

    # ---------------- Internal helpers (formerly standalone utilities) --------
    def _fetch_recent(self) -> list[FeedParserDict]:
        """Fetch recent feed entries newer than the configured cutoff."""
        tz = timezone(self.tz_name)
        now_local = tz.localize(datetime.now())
        cutoff = now_local - timedelta(hours=self.hours, minutes=self.grace_minutes)
        feed = feedparser.parse(self.rss_url, modified=cutoff.utctimetuple())
        fresh = [e for e in feed.entries if parse(e.published) > cutoff]
        logger.info("Fetched %d fresh entries (cutoff %s)", len(fresh), cutoff.isoformat())
        return fresh

    def _resolve_links(self, entries: list[FeedParserDict]) -> None:
        """Resolve HTTP redirects for entry links concurrently (in-place)."""
        if not entries:
            return
        session = requests.Session()

        def head(url: str) -> str:
            try:
                r = session.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT)
                r.raise_for_status()
                return r.url
            except Exception as exc:
                logger.debug("HEAD failed for %s (%s); keeping original", url, exc)
                return url

        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            future_map = {executor.submit(head, e.link): e for e in entries}
            for fut in as_completed(future_map):
                entry = future_map[fut]
                entry.link = fut.result()

    def _fetch_images(self, entries: list[FeedParserDict]) -> None:
        """Download images for entries and attach PIL Image objects (in-place)."""
        if not entries:
            return
        session = requests.Session()
        headers = {'User-Agent': 'Mozilla/5.0'}

        def load(e: FeedParserDict):
            href = getattr(e, 'href', None)
            if not href or href.lower().endswith('nophoto.png'):
                e.image = None
                return
            try:
                r = session.get(href, timeout=REQUEST_TIMEOUT, headers=headers)
                r.raise_for_status()
                from io import BytesIO
                e.image = Image.open(BytesIO(r.content))
            except (requests.RequestException, UnidentifiedImageError, OSError) as exc:
                logger.debug("Image load failed for %s (%s)", href, exc)
                e.image = None

        with ThreadPoolExecutor(max_workers=self.threads) as ex:
            ex.map(load, entries)

    @staticmethod
    def _compute_hash(entry: LzxEntry) -> None:
        """Compute perceptual (average) hash for an entry image if available."""
        if entry.image and entry.image_hash is None:
            try:
                entry.image_hash = imagehash.average_hash(entry.image, IMAGE_HASH_SIZE)
            except Exception as exc:
                logger.debug("Hash failed for %s (%s)", entry.href, exc)
                entry.image_hash = None

    def _wrap(self, entries: Sequence[FeedParserDict]) -> list[LzxEntry]:
        """Wrap raw feed entries in LzxEntry objects and compute image hashes."""
        wrapped = [
            LzxEntry(
                raw=e,
                link=e.link,
                title=e.title,
                published=e.published,
                summary=e.summary,
                href=getattr(e, 'href', None),
            )
            for e in entries
        ]
        # Attach images already fetched
        for w in wrapped:
            if img_attr := getattr(w.raw, 'image', None):
                w.image = img_attr
            self._compute_hash(w)
        return wrapped

    def _group(
            self,
            entries: list[FeedParserDict],
            *,
            require_same_price: bool,
            similarity_threshold: float
    ) -> list[list[FeedParserDict]]:
        """Group entries by normalized title (+ price if required) and image similarity."""
        if not entries:
            return []
        wrapped = self._wrap(entries)
        groups: list[list[FeedParserDict]] = []  # store only raw entries per spec
        remaining = wrapped.copy()
        while remaining:
            base = remaining.pop()
            current_group_raw: list[FeedParserDict] = [base.raw]
            survivors: list[LzxEntry] = []
            for other in remaining:
                if base.normalized_title != other.normalized_title:
                    survivors.append(other)
                    continue
                if require_same_price and base.summary != other.summary:
                    survivors.append(other)
                    continue
                duplicate = True
                if base.image_hash and other.image_hash:
                    dist = (base.image_hash - other.image_hash) / base.image_hash.hash.size
                    duplicate = dist <= similarity_threshold
                if duplicate:
                    current_group_raw.append(other.raw)
                else:
                    survivors.append(other)
            remaining = survivors
            groups.append(current_group_raw)
        return groups

    @staticmethod
    def _entry_to_dict(entry: FeedParserDict) -> dict[str, Any]:
        """Convert a feed entry into a lightweight export-friendly dict."""
        dt = parse(entry.published)
        date_str = format_date(dt, format='medium', locale=DEFAULT_LOCALE)
        return {
            "image": getattr(entry, 'href', None),
            "link": entry.link,
            "price": entry.summary,
            "date": date_str,
            "name": entry.title
        }

    # ---------------- Public API (stable) ------------------------------------
    def fetch(self) -> list[FeedParserDict]:
        """Fetch recent raw feed entries (no enrichment)."""
        return self._fetch_recent()

    def enrich(self, entries: list[FeedParserDict]) -> list[FeedParserDict]:
        """Resolve redirects and fetch images for given entries."""
        self._resolve_links(entries)
        self._fetch_images(entries)
        return entries

    def get_offers(self) -> list[FeedParserDict]:
        """Convenience: fetch then enrich recent entries."""
        entries = self.fetch()
        return self.enrich(entries)

    def group(
            self,
            entries: list[FeedParserDict],
            *,
            require_same_price: bool = True,
            similarity_threshold: float = IMAGE_SIMILARITY_THRESHOLD
    ) -> list[list[FeedParserDict]]:
        """Return grouped entries sharing title (+ price) and similar images."""
        return self._group(
            entries,
            require_same_price=require_same_price,
            similarity_threshold=similarity_threshold
        )

    def offers_to_dict(self, entries: list[FeedParserDict]) -> list[dict[str, Any]]:
        """Map entries to export dicts (flat structure)."""
        return [self._entry_to_dict(e) for e in entries]

    def get_unique(self, entries: list[FeedParserDict]) -> list[dict[str, Any]]:
        """Return offers that have no duplicates under grouping rules."""
        groups = self.group(entries)
        return [self._entry_to_dict(g[0]) for g in groups if len(g) == 1]

    def get_duplicates(self, entries: list[FeedParserDict]) -> list[list[dict[str, Any]]]:
        """Return grouped duplicate offers (each inner list is a duplicate cluster)."""
        groups = self.group(entries)
        return [[self._entry_to_dict(e) for e in g] for g in groups if len(g) > 1]
