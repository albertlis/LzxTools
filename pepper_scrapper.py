import logging
import os
import platform
from dataclasses import dataclass
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from scrapper_base import ScrapperBase


@dataclass(frozen=True, slots=True)
class PepperOffer:
    name: str
    link: str
    image: str


class PepperScrapper(ScrapperBase):
    def __init__(self):
        super().__init__(cache_path=Path('pepper_cache.pkl.zstd'))
        self.skip_cookies_locator = (By.XPATH, "//button[.//span[contains(text(), 'Kontynuuj bez akceptacji')]]")
        self.hottest_offers_locator = (By.CLASS_NAME, "scrollBox-item.card-item.width--all-12")
        self.hottest_offers_pages_locator = (By.CSS_SELECTOR, "ol.lbox--v-2 > li > button")
        self.link = os.getenv('PEPPER_URL')

    @staticmethod
    def get_driver() -> webdriver.Chrome:
        system = platform.system()
        if system not in {"Windows", "Linux"}:
            raise ValueError("This driver only works on Windows and Linux systems.")

        browser = 'chrome' if system == "Linux" else 'edge'

        options = webdriver.ChromeOptions() if browser == 'chrome' else webdriver.EdgeOptions()
        options.add_argument("window-size=1400,1080")
        options.add_argument("--disk-cache-size=10485760")
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--log-level=3')
        options.add_argument('--no-sandbox')
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-plugins-discovery")

        if browser == 'chrome':
            options.binary_location = "/usr/bin/chromium-browser"
        # Disable loading images for better performance
        prefs = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/58.0.3029.110 Safari/2b7c7"
        )
        if browser == "chrome":
            return webdriver.Chrome(options, Service(executable_path="/usr/bin/chromedriver"))
        else:
            return webdriver.Chrome(options=options)

    @staticmethod
    def click_element(wait: WebDriverWait, element: tuple[str, str]):
        button = wait.until(EC.element_to_be_clickable(element))
        button.click()
        logging.debug(f'Clicked {element=}')

    def get_hottest_pepper_offers(self) -> list[PepperOffer]:
        driver = self.get_driver()
        driver.get(self.link)
        wait = WebDriverWait(driver, 20)
        self.click_element(wait, self.skip_cookies_locator)

        pagination_buttons = wait.until(EC.presence_of_all_elements_located(self.hottest_offers_pages_locator))
        logging.debug(f'Found {len(pagination_buttons)} hottest offers pages')
        all_hottest_offers = []

        for page_index in range(len(pagination_buttons)):
            # Refresh the list of pagination buttons
            pagination_buttons = wait.until(EC.presence_of_all_elements_located(self.hottest_offers_pages_locator))
            if page_index > 0:
                pagination_buttons[page_index].click()
                logging.debug(f'Clicked {page_index} page button')

            items = wait.until(EC.presence_of_all_elements_located(self.hottest_offers_locator))
            # Extract information from each item
            for item in items:
                link_element = item.find_element(By.TAG_NAME, "a")
                href = link_element.get_attribute("href")
                title = link_element.get_attribute("title")
                image_element = item.find_element(By.TAG_NAME, "img")
                image_src = image_element.get_attribute("src")

                if (offer := PepperOffer(title, href, image_src)) not in self.cache:
                    logging.info(f'Found new {offer=}')
                    self.cache.add(offer)
                    all_hottest_offers.append(offer)
                # offer = PepperOffer(title, href, image_src)
                # all_hottest_offers.append(offer)
        driver.close()
        return all_hottest_offers

    def new_offers_to_dict(self, new_offers: list[PepperOffer]) -> list[dict[str, str]]:
        return [offer.__dict__ for offer in new_offers]
