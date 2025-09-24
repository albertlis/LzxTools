import contextlib
import logging
import pickle
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable, Any

from zstandard import ZstdDecompressor, ZstdCompressor

# Constants to prevent magic literals scattered in the code.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
)
ZSTD_COMPRESSION_LEVEL = 10  # Reasonable balance; adjust if needed.


class ScrapperBase(ABC):
    """
    Abstract base class for scrapers that maintain a persistent cache of seen items.

    Responsibilities:
    - Manage an optional on-disk cache (compressed + pickled).
    - Provide a standard header set (e.g., user-agent) for HTTP requests.
    - Define an abstract transformation method for new offers.

    Usage:
        with ConcreteScrapper(cache_path=Path("cache.pkl.zstd")) as s:
            # operate on s.cache or use s.update_cache(...)
            ...

    Attributes:
        cache_path (Path | None): Location of the persistent cache file if provided.
        cache (set[Any] | None): In-memory cache of processed identifiers/items.
        headers (dict[str, str]): Default HTTP headers.
        _dirty (bool): Tracks whether the cache has been modified since last save.
    """

    def __init__(self, cache_path: Path | None = None) -> None:
        super().__init__()
        self.cache_path: Path | None = cache_path
        self.cache: set[Any] | None = self.load_cache() if cache_path else None
        self.headers: dict[str, str] = {'User-Agent': DEFAULT_USER_AGENT}
        self._dirty: bool = False  # Only write cache when something actually changed.

    @staticmethod
    @abstractmethod
    def new_offers_to_dict(new_offers) -> list[dict[str, str]]:
        """
        Transform raw 'new offers' data into a normalized list of dictionaries.

        Implementations should:
            - Validate expected fields.
            - Normalize data types / keys.
            - Return a list[dict[str, str]] suitable for downstream processing.

        Args:
            new_offers: Source data structure containing newly scraped offers.

        Returns:
            list[dict[str, str]]: Normalized offer records.
        """
        pass  # pragma: no cover - abstract method

    def load_cache(self) -> set[Any]:
        """
        Load and deserialize the cache from disk if present.

        Returns:
            set[Any]: A set representing the cached items (empty set if none or invalid).

        Notes:
            - If the cache file is corrupted or unreadable, it logs a warning and starts fresh.
        """
        # cache_path is guaranteed not None when called.
        if self.cache_path and self.cache_path.exists():
            try:
                logging.debug(f"Loading cached data: {self.cache_path.resolve()}")
                with open(self.cache_path, 'rb') as f:
                    raw = f.read()
                data = ZstdDecompressor().decompress(raw)
                cache_obj = pickle.loads(data)
                if not isinstance(cache_obj, set):
                    logging.warning("Cache content is not a set. Reinitializing empty cache.")
                    return set()
                return cache_obj
            except Exception as exc:  # Broad catch to ensure resilience.
                logging.warning(f"Failed to load cache ({exc}). Starting with empty cache.")
                return set()
        if self.cache_path:
            logging.debug(f"No cache found in: {self.cache_path.resolve()}")
        return set()

    def save_cache(self, force: bool = False) -> None:
        """
        Persist the in-memory cache to disk (compressed).

        Args:
            force (bool): If True, forces a write even if not marked dirty.

        Behavior:
            - No-op if cache_path or cache is None.
            - Skips write if nothing changed unless force=True.
        """
        if not self.cache_path or self.cache is None:
            return
        if not self._dirty and not force:
            logging.debug("Cache unchanged; skipping save.")
            return
        try:
            data = pickle.dumps(self.cache, protocol=pickle.HIGHEST_PROTOCOL)
            data = ZstdCompressor(level=ZSTD_COMPRESSION_LEVEL).compress(data)
            with open(self.cache_path, 'wb') as f:
                f.write(data)
            logging.debug(f"Saved cache data: {self.cache_path.resolve()}")
            self._dirty = False
        except Exception as exc:
            logging.error(f"Failed to save cache ({exc}).")

    def update_cache(self, items: Iterable[Any]) -> None:
        """
        Add items to the cache and mark it dirty.

        Args:
            items (Iterable[Any]): Items to be added to the cache set.

        Notes:
            - Initializes cache as an empty set if not present.
        """
        if self.cache is None:
            self.cache = set()
        before = len(self.cache)
        self.cache.update(items)
        if len(self.cache) != before:
            self._dirty = True
            logging.debug(f"Cache updated (+{len(self.cache) - before}). Size now: {len(self.cache)}")

    def __enter__(self):
        """
        Enter context manager. Returns self for usage with 'with' statements.
        """
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        """
        Ensure cache persistence on context exit.

        Saves the cache unless an exception occurred (still saves if force desired).
        """
        # Optionally skip save on exceptions; adjust policy if needed.
        if exc_type is None:
            self.save_cache()

    def __del__(self):
        """
        Destructor fallback to persist cache.

        Warning:
            __del__ is not guaranteed to run (e.g., interpreter shutdown order),
            hence context manager or explicit save_cache() is preferred.
        """
        with contextlib.suppress(Exception):
            if self.cache_path:
                self.save_cache()
