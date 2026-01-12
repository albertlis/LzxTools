import logging
import os
import platform
from dataclasses import dataclass
from pathlib import Path
import contextlib
from contextlib import contextmanager  # added

from playwright.sync_api import sync_playwright, Page, BrowserContext, Route, Request

from scrapper_base import ScrapperBase


@dataclass(frozen=True, slots=True)
class PepperOffer:
    """
    Immutable representation of a Pepper offer.

    Fields:
        name: Human readable title (optionally enriched with price).
        link: Direct URL to the offer.
        image: Image URL (may be None if filtered or missing).
    """
    name: str
    link: str
    image: str | None


class PepperScrapper(ScrapperBase):
    """
    Scraper for Pepper offers using Playwright (synchronous API).

    Responsibilities:
        - Navigate to Pepper najgoretsze page.
        - Accept (or bypass) cookie dialog.
        - Extract offer title, link, image and price.
        - Maintain a de-duplicated cache via ScrapperBase.

    Notes:
        - Images are blocked at network layer for performance.
        - Returns only offers not yet present in cache.
    """

    # New small configuration constants
    _PAGE_PATHS: tuple[str, ...] = ("", "?page=2")
    _NAV_TIMEOUT_MS = 25_000
    _POST_NAV_SLEEP_MS = 500

    def __init__(self) -> None:
        super().__init__(cache_path=Path('pepper_cache.pkl.zstd'))
        self.link: str = os.getenv('PEPPER_URL', 'https://www.pepper.pl/najgoretsze')
        # Updated CSS selectors for current website structure
        self._offer_container_selector = "article.thread"
        self._title_selector = "strong.thread-title a.thread-link"
        self._price_selector = "span.thread-price"
        self._image_selector = "img.thread-image"
        self._skip_cookies_xpath = "//button[.//span[contains(text(), 'Kontynuuj bez akceptacji')]]"

    def _block_unwanted(self, route: Route, request: Request) -> None:
        """
        Network routing callback to abort loading of images and media for performance.
        """
        if request.resource_type in {"image", "media", "font"}:
            return route.abort()
        return route.continue_()

    @contextmanager
    def _browser_session(self):
        """
        Managed Playwright session yielding a ready page with routing configured.
        Guarantees full teardown even on exceptions.
        """
        playwright = browser = context = page = None
        try:
            system = platform.system()
            channel = "msedge" if system == "Windows" else "chromium"
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(
                channel=channel if channel != "chromium" else None,
                headless=True,
                args=[
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--disable-sync",
                    "--disable-translate",
                ],
            )
            context = browser.new_context(
                user_agent=self.headers['User-Agent'],
                viewport={"width": 1400, "height": 1080},
                java_script_enabled=True,
            )
            context.route("**/*", self._block_unwanted)
            page = context.new_page()
            yield page
        finally:
            with contextlib.suppress(Exception):
                if page:
                    page.close()
                if context:
                    context.close()
                if browser:
                    browser.close()
                if playwright:
                    playwright.stop()

    def _dismiss_cookie_banner(self, page: Page) -> None:
        """
        Attempt to dismiss the cookie dialog; silent on failure.
        """
        try:
            locator = page.locator(f"xpath={self._skip_cookies_xpath}").first
            locator.wait_for(timeout=4_000)
            locator.click()
            logging.debug("Dismissed cookie dialog.")
        except Exception:
            logging.debug("Cookie dialog not found or already dismissed.")

    @staticmethod
    def _switch_to_weekly(page: Page) -> None:
        """
        Open the timeframe dropdown (currently showing 'Dzisiaj' or other)
        and select 'Tydzień' (button[value='week']).
        Silent on failure.
        """
        try:
            # Try to detect if already set to 'Tydzień'
            dropdown = page.locator("#threadListingDescriptionPortal button.aGrid").first
            with contextlib.suppress(Exception):
                if "Tydzień" in (dropdown.inner_text() or ""):
                    return

            # Open dropdown
            dropdown.click()
            # Wait for the popover and click 'Tydzień'
            week_btn = page.locator("section.popover--dropdown button[value='week']").first
            week_btn.wait_for(state="visible", timeout=5_000)
            week_btn.click()

            # Best-effort: wait until label shows 'Tydzień'
            with contextlib.suppress(Exception):
                page.locator("#threadListingDescriptionPortal button.aGrid:has-text('Tydzień')").wait_for(timeout=3_000)
        except Exception as exc:
            logging.debug(f"Failed to switch to weekly timeframe: {exc}")

    def _extract_offers_from_current_page(self, page) -> list[PepperOffer]:
        """Parse currently loaded page and return PepperOffer objects (without cache filtering)."""
        offers: list[PepperOffer] = []
        offer_elements = page.locator(self._offer_container_selector)
        count = offer_elements.count()
        logging.debug(f"Detected {count} offer containers.")
        for idx in range(count):
            container = offer_elements.nth(idx)
            try:
                title_el = container.locator(self._title_selector)
                if not title_el.count():
                    continue
                title_text = title_el.inner_text().strip()
                link = title_el.get_attribute("href") or ""
                if link and not link.startswith('http'):
                    link = f"https://www.pepper.pl{link}"
                price_el = container.locator(self._price_selector)
                price_text = price_el.inner_text().strip() if price_el.count() else ""
                image_el = container.locator(self._image_selector)
                image_src = image_el.get_attribute("src") if image_el.count() else None
                full_name = f"{title_text}, {price_text}" if price_text else title_text
                offers.append(PepperOffer(full_name, link, image_src))
            except Exception as exc:
                logging.debug(f"Failed parsing offer index {idx}: {exc}")
        return offers

    def get_hottest_pepper_offers(self) -> list[PepperOffer]:
        """
        Scrape Pepper 'Najgorętsze' (first two pages) and return newly discovered offers (not in cache).
        Refactored for clarity and safer resource handling.
        """
        base = self.link.split('?')[0]
        target_pages = [f"{base}{suffix}" for suffix in self._PAGE_PATHS]
        logging.debug(f"Pages to scrape: {target_pages}")

        aggregated: dict[str, PepperOffer] = {}

        with self._browser_session() as page:
            for idx, url in enumerate(target_pages):
                logging.debug(f"Navigating to {url}")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=self._NAV_TIMEOUT_MS)
                except Exception as exc:
                    logging.warning(f"Navigation failed ({url}): {exc}")
                    continue

                if idx == 0:
                    self._dismiss_cookie_banner(page)

                # Switch to 'Tydzień' timeframe
                self._switch_to_weekly(page)

                # Small pause to let dynamic content settle
                page.wait_for_timeout(self._POST_NAV_SLEEP_MS)
                with contextlib.suppress(Exception):
                    page.wait_for_selector(self._offer_container_selector, timeout=10_000)

                for offer in self._extract_offers_from_current_page(page):
                    # Deduplicate across pages by link
                    if offer.link and offer.link not in aggregated:
                        aggregated[offer.link] = offer

        if not aggregated:
            logging.debug("No offers extracted.")
            return []

        # Cache filtering (use set for O(1) membership if cache exists)
        cached: set[PepperOffer] = set(self.cache) if self.cache else set()
        new_offers = [offer for offer in aggregated.values() if offer not in cached]

        for offer in new_offers:
            logging.info(f"New Pepper offer: {offer.name}")

        if new_offers:
            self.update_cache(new_offers)

        return new_offers

    @staticmethod
    def new_offers_to_dict(new_offers: list[PepperOffer]) -> list[dict[str, str]]:
        """
        Convert PepperOffer objects into serializable dictionaries.

        Args:
            new_offers: list of PepperOffer instances.

        Returns:
            list[dict[str, str]]: Plain dictionaries for downstream usage.
        """
        return [
            {
                "name": offer.name,
                "link": offer.link,
                "image": offer.image or "",
            }
            for offer in new_offers
        ]
