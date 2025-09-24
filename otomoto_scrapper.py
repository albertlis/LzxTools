"""Scraper utilities for extracting vehicle offers from otomoto.pl search result pages."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import requests
from bs4 import BeautifulSoup, Tag

from scrapper_base import ScrapperBase


@dataclass(frozen=True, slots=True)
class OtomotoOffer:
    """Immutable representation of a single Otomoto listing.

    Fields:
        title: Raw title text of the offer.
        link: Absolute or relative URL to the offer details page.
        year: Production year (string form, may be empty).
        mileage: Mileage information (string form, may be empty).
        image_link: URL of the primary image (may be None if absent).
        price: Price text including currency (may be empty if not parsed).
    """

    title: str
    link: str
    year: str
    mileage: str
    image_link: Optional[str]
    price: str

    def to_dict(self) -> dict[str, str]:
        """Convert the offer into a flat dict suitable for serialization / UI."""
        return {
            "name": f"{self.title}, {self.year}, {self.mileage}",
            "image": self.image_link or "",
            "link": self.link,
            "price": self.price,
        }


class OtomotoScrapper(ScrapperBase):
    """Scraper for otomoto.pl listings with simple in-memory + persisted cache to skip repeats."""
    _CACHE_FILE = Path("otomoto_cache.pkl.zstd")
    _SEARCH_RESULTS_ATTR = {"data-testid": "search-results"}
    _ARTICLE_FILTER = {"data-media-size": "small", "data-orientation": "horizontal"}
    _REQUEST_TIMEOUT = 15  # seconds

    def __init__(self, link: str):
        """
        Args:
            link: Fully constructed otomoto.pl search URL.
        """
        super().__init__(cache_path=self._CACHE_FILE)
        self.link = link
        self._session = requests.Session()

    def get_offers(self) -> list[OtomotoOffer]:
        """Fetch page, parse all offers, return only offers not already in cache."""
        soup = self._fetch_page()
        if soup is None:
            return []

        container = soup.find("div", self._SEARCH_RESULTS_ATTR)
        if container is None:
            logging.warning("Otomoto: search results container not found")
            return []

        articles = container.find_all("article", self._ARTICLE_FILTER)
        if not articles:
            logging.info("Otomoto: no article elements found")
            return []

        new_offers: list[OtomotoOffer] = []
        for article in articles:
            offer = self._parse_article(article)
            if not offer:
                continue
            if offer not in self.cache:
                logging.info("Otomoto: new offer %s", offer)
                new_offers.append(offer)
                self.cache.add(offer)
        return new_offers

    def new_offers_to_dict(self, new_offers: list[OtomotoOffer]) -> list[dict[str, str]]:
        """Utility to convert a list of new offers into serializable dicts."""
        return [o.to_dict() for o in new_offers]

    # ----------------- Internal helpers -----------------

    def _fetch_page(self) -> Optional[BeautifulSoup]:
        """Perform HTTP GET and return BeautifulSoup parsed document or None on failure."""
        try:
            resp = self._session.get(self.link, headers=self.headers, timeout=self._REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logging.error("Otomoto: HTTP request failed: %s", exc)
            return None
        return BeautifulSoup(resp.content, "html.parser")

    def _parse_article(self, article: Tag) -> Optional[OtomotoOffer]:
        """Extract an OtomotoOffer from an <article> tag or return None if mandatory parts missing."""
        try:
            title_anchor = article.find("p").find("a", href=True)  # type: ignore[union-attr]
        except AttributeError:
            logging.debug("Otomoto: title anchor not found in article")
            return None
        title = title_anchor.get_text(strip=True)
        link = title_anchor["href"]

        params = self._extract_parameters(article)
        year = params.get("year", "")
        mileage = params.get("mileage", "")

        image_tag = article.find("img")
        image_url = image_tag.get("src") if image_tag else None

        price = self._extract_price(article)
        if not price:
            logging.debug("Otomoto: price missing for link=%s", link)

        return OtomotoOffer(
            title=title,
            link=link,
            year=year,
            mileage=mileage,
            image_link=image_url,
            price=price or "",
        )

    def _extract_parameters(self, article: Tag) -> dict[str, str]:
        """Collect parameter <dd> elements keyed by their 'data-parameter' attribute."""
        params: dict[str, str] = {}
        for param in article.find_all("dd", {"data-parameter": True}):
            if key := param.get("data-parameter"):
                params[key] = param.get_text(strip=True)
        return params

    def _extract_price(self, article: Tag) -> str:
        """Best-effort extraction of price text; returns empty string if not found."""
        # Strategy: look for h3 with price inside any div; fallback: any tag containing 'PLN'
        # Narrow first
        for div in article.find_all("div"):
            h3 = div.find("h3")
            if not h3:
                continue
            text = h3.get_text(" ", strip=True)
            if "PLN" in text:
                return text
        # Fallback broad search
        price_candidate = article.find(string=lambda t: isinstance(t, str) and "PLN" in t)
        return price_candidate.strip() if price_candidate else ""
