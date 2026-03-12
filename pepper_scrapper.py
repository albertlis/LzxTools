import logging
import os
import platform
import random
import time
from dataclasses import dataclass
from pathlib import Path
import contextlib
from contextlib import contextmanager

from playwright.sync_api import sync_playwright, Page, Route, Request
from playwright_stealth.stealth import Stealth

from scrapper_base import ScrapperBase

# ---------------------------------------------------------------------------
# Browser identity – Chrome 131 on Windows 10 x64
# ---------------------------------------------------------------------------
_CHROME_VERSION = "131.0.0.0"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/{_CHROME_VERSION} Safari/537.36"
)

# Stealth will derive the correct Sec-CH-UA from the UA string automatically.
# We only set headers that stealth does NOT handle itself.
_EXTRA_HEADERS: dict[str, str] = {
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "DNT": "1",
}

# ---------------------------------------------------------------------------
# Stealth configuration
# Stealth.use_sync() hooks sync_playwright() so that every browser.launch(),
# browser.new_context() and browser.new_page() automatically gets all
# evasion init scripts injected and CLI args patched.
# ---------------------------------------------------------------------------
_STEALTH = Stealth(
    navigator_user_agent_override=_USER_AGENT,
    navigator_languages_override=("pl-PL", "pl"),
    navigator_platform_override="Win32",
    navigator_vendor_override="Google Inc.",
    webgl_vendor_override="Intel Inc.",
    webgl_renderer_override="Intel Iris OpenGL Engine",
    navigator_hardware_concurrency=8,
    # All evasion modules enabled (defaults):
    chrome_app=True,
    chrome_csi=True,
    chrome_load_times=True,
    chrome_runtime=False,   # chrome.runtime injection can break some sites
    hairline=True,
    iframe_content_window=True,
    media_codecs=True,
    navigator_languages=True,
    navigator_permissions=True,
    navigator_platform=True,
    navigator_plugins=True,
    navigator_user_agent=True,
    navigator_vendor=True,
    navigator_webdriver=True,
    error_prototype=True,
    sec_ch_ua=True,
    webgl_vendor=True,
)


@dataclass(frozen=True, slots=True)
class PepperOffer:
    """
    Immutable representation of a Pepper offer.

    Fields:
        name:  Human readable title (optionally enriched with price).
        link:  Direct URL to the offer.
        image: Image URL (may be None if missing).
    """

    name: str
    link: str
    image: str | None


class PepperScrapper(ScrapperBase):
    """
    Scraper for Pepper offers using Playwright (synchronous API) with
    playwright-stealth applied via the canonical Stealth.use_sync() API.

    Anti-bot measures:
        - Stealth.use_sync() wraps sync_playwright() – all evasion scripts
          are injected automatically on every page via add_init_script.
        - --disable-blink-features=AutomationControlled and --accept-lang
          CLI args patched automatically by stealth.
        - Realistic User-Agent, Sec-CH-UA (derived by stealth), Accept-Language.
        - Polish locale + Europe/Warsaw timezone in browser context.
        - Real browser channel (msedge on Windows) for maximum authenticity.
        - Human-like random delays and mouse scroll between pages.
    """

    _PAGE_PATHS: tuple[str, ...] = ("", "?page=2")
    _NAV_TIMEOUT_MS = 30_000
    _POST_NAV_SLEEP_MS = 800

    def __init__(self) -> None:
        super().__init__(cache_path=Path("pepper_cache.pkl.zstd"))
        self.link: str = os.getenv("PEPPER_URL", "https://www.pepper.pl/najgoretsze")
        self._offer_container_selector = "article.thread"
        self._title_selector = "strong.thread-title a.thread-link"
        self._price_selector = "span.thread-price"
        self._image_selector = "img.thread-image"
        self._skip_cookies_selector = "button[data-t='rejectAll']"

    # ------------------------------------------------------------------
    # Network routing
    # ------------------------------------------------------------------

    def _block_unwanted(self, route: Route, request: Request) -> None:
        """Abort image, media and font requests for performance."""
        if request.resource_type in {"image", "media", "font"}:
            route.abort()
        else:
            route.continue_()

    # ------------------------------------------------------------------
    # Human-like interaction helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _human_delay(lo: float = 0.3, hi: float = 1.2) -> None:
        """Sleep for a random interval to mimic human reaction time."""
        time.sleep(random.uniform(lo, hi))

    @staticmethod
    def _human_scroll(page: Page) -> None:
        """Perform a few randomised scroll steps to emulate reading."""
        steps = random.randint(3, 6)
        for _ in range(steps):
            page.mouse.wheel(0, random.randint(200, 600))
            time.sleep(random.uniform(0.05, 0.25))

    # ------------------------------------------------------------------
    # Browser session
    # ------------------------------------------------------------------

    @contextmanager
    def _browser_session(self):
        """
        Managed Playwright session with stealth applied via Stealth.use_sync().
        Yields a ready Page; guarantees cleanup on exit.
        """
        browser = context = page = None
        channel = "msedge" if platform.system() == "Windows" else None

        with _STEALTH.use_sync(sync_playwright()) as p:
            try:
                browser = p.chromium.launch(
                    channel=channel,
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
                        "--disable-infobars",
                        "--window-size=1920,1080",
                    ],
                )

                context = browser.new_context(
                    viewport={"width": 1400, "height": 1080},
                    screen={"width": 1920, "height": 1080},
                    device_scale_factor=1.0,
                    locale="pl-PL",
                    timezone_id="Europe/Warsaw",
                    color_scheme="light",
                    extra_http_headers=_EXTRA_HEADERS,
                    accept_downloads=False,
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

    # ------------------------------------------------------------------
    # Cookie banner
    # ------------------------------------------------------------------

    def _dismiss_cookie_banner(self, page: Page) -> None:
        """Attempt to dismiss the cookie dialog; silent on failure."""
        try:
            locator = page.locator(self._skip_cookies_selector).first
            locator.wait_for(timeout=5_000)
            self._human_delay(0.4, 0.9)
            locator.click()
            logging.debug("Dismissed cookie dialog.")
            self._human_delay(0.3, 0.7)
        except Exception:
            logging.debug("Cookie dialog not found or already dismissed.")

    # ------------------------------------------------------------------
    # Timeframe switch
    # ------------------------------------------------------------------

    @staticmethod
    def _switch_to_weekly(page: Page) -> None:
        """
        Open the timeframe dropdown and select 'Tydzień' (button[value='week']).
        Silent on failure.
        """
        try:
            dropdown = page.locator("#threadListingDescriptionPortal button.aGrid").first
            with contextlib.suppress(Exception):
                if "Tydzień" in (dropdown.inner_text() or ""):
                    return
            dropdown.click()
            week_btn = page.locator("section.popover--dropdown button[value='week']").first
            week_btn.wait_for(state="visible", timeout=5_000)
            week_btn.click()
            with contextlib.suppress(Exception):
                page.locator(
                    "#threadListingDescriptionPortal button.aGrid:has-text('Tydzień')"
                ).wait_for(timeout=3_000)
        except Exception as exc:
            logging.debug(f"Failed to switch to weekly timeframe: {exc}")

    # ------------------------------------------------------------------
    # Offer extraction
    # ------------------------------------------------------------------

    def _extract_offers_from_current_page(self, page: Page) -> list[PepperOffer]:
        """Parse the currently loaded page and return PepperOffer objects."""
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
                if link and not link.startswith("http"):
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_hottest_pepper_offers(self) -> list[PepperOffer]:
        """
        Scrape Pepper 'Najgorętsze' (first two pages) and return
        newly discovered offers not yet present in cache.
        """
        base = self.link.split("?")[0]
        target_pages = [f"{base}{suffix}" for suffix in self._PAGE_PATHS]
        logging.debug(f"Pages to scrape: {target_pages}")

        aggregated: dict[str, PepperOffer] = {}

        total_pages = len(target_pages)
        with self._browser_session() as page:
            for idx, url in enumerate(target_pages):
                logging.info(f"[{idx + 1}/{total_pages}] Navigating to: {url}")
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=self._NAV_TIMEOUT_MS)
                    logging.info(f"[{idx + 1}/{total_pages}] Page loaded.")
                except Exception as exc:
                    logging.warning(f"[{idx + 1}/{total_pages}] Navigation failed ({url}): {exc}")
                    continue

                if idx == 0:
                    logging.debug("Attempting to dismiss cookie banner...")
                    self._dismiss_cookie_banner(page)
                    logging.debug("Attempting to switch to weekly view...")
                    self._switch_to_weekly(page)

                self._human_delay(0.5, 1.5)
                self._human_scroll(page)
                page.wait_for_timeout(self._POST_NAV_SLEEP_MS + random.randint(0, 400))
                with contextlib.suppress(Exception):
                    page.wait_for_selector(self._offer_container_selector, timeout=10_000)

                before = len(aggregated)
                for offer in self._extract_offers_from_current_page(page):
                    if offer.link and offer.link not in aggregated:
                        aggregated[offer.link] = offer
                found_on_page = len(aggregated) - before
                logging.info(
                    f"[{idx + 1}/{total_pages}] Found {found_on_page} new offers on page "
                    f"(total: {len(aggregated)})."
                )

                if idx < len(target_pages) - 1:
                    logging.debug(f"Waiting before page {idx + 2}...")
                    self._human_delay(1.0, 2.5)

        if not aggregated:
            logging.debug("No offers extracted.")
            return []

        cached: set[PepperOffer] = set(self.cache) if self.cache else set()
        new_offers = [offer for offer in aggregated.values() if offer not in cached]

        for offer in new_offers:
            logging.info(f"New Pepper offer: {offer.name}")

        if new_offers:
            self.update_cache(new_offers)

        return new_offers

    # ------------------------------------------------------------------

    @staticmethod
    def new_offers_to_dict(new_offers: list[PepperOffer]) -> list[dict[str, str]]:
        """Convert PepperOffer objects into serializable dictionaries."""
        return [
            {
                "name": offer.name,
                "link": offer.link,
                "image": offer.image or "",
            }
            for offer in new_offers
        ]
