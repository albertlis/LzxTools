import logging
import re
import time
import urllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.error import HTTPError

import feedparser
import imagehash
import requests
import schedule
import yagmail
import yaml
from PIL import Image
from babel.dates import format_date
from dateutil.parser import parse
from easydict import EasyDict
from feedparser import FeedParserDict
from jinja2 import Template
from pytz import timezone
from collections import namedtuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.wait import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support import expected_conditions as EC

URL = r'https://www.pepper.pl'
CHROME_DRIVER_PATH = ChromeDriverManager().install()
SKIP_COOKIES = (By.XPATH, "//button[.//span[contains(text(), 'Kontynuuj bez akceptacji')]]")
HOTTEST_OFFERS = (By.CLASS_NAME, "scrollBox-item.card-item.width--all-12")
HOTTEST_OFFERS_PAGES = (By.CSS_SELECTOR, "ol.lbox--v-2 > li > button")

with open('secrets.yml', 'rt') as f:
    secrets = yaml.safe_load(f)

LZX_RSS_URL = secrets['lzx_rss_url']
PEPPER_RSS_URL = secrets['pepper_rss_url']


def parse_date(datetime_str: str) -> str:
    datetime_obj = parse(datetime_str)
    return format_date(datetime_obj, format='medium', locale='pl_PL')


def get_last_day_entries(rss_url: str) -> list[FeedParserDict]:
    warsaw = timezone('Europe/Warsaw')
    time_24h_ago = warsaw.localize(datetime.now() - timedelta(hours=24, minutes=10))

    feed = feedparser.parse(rss_url, modified=time_24h_ago.strftime('%a, %d %b %Y %H:%M:%S %Z'))
    return [entry for entry in feed.entries if parse(entry.published) > time_24h_ago]


def get_direct_link(item: FeedParserDict) -> FeedParserDict:
    url = item.link
    response = requests.head(url, allow_redirects=True)  # , verify=False)
    item['link'] = response.url
    return item


def assign_direct_offers_links(entries: list[FeedParserDict]) -> list[FeedParserDict]:
    with ThreadPoolExecutor() as executor:
        return list(executor.map(get_direct_link, entries))


def assign_images_lzx(entries: list[FeedParserDict]) -> list[FeedParserDict]:
    for entry in entries:
        try:
            if entry.href.lower().endswith('nophoto.png'):
                entry.image = None
                continue
            req = urllib.request.Request(entry.href, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as url:
                entry.image = Image.open(url)
        except HTTPError:
            print(entry.href)
            entry.image = None
    return entries


def remove_special_characters(input_string: str) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', input_string).lower()


def group_entries(entries: list[FeedParserDict]) -> list[list[FeedParserDict]]:
    entries_c = entries.copy()
    grouped_offers = []
    # is_same_price = entry.summary == entry_2.summary
    # TODO: set option
    is_same_price = True
    while entries_c:
        entry = entries_c.pop()
        group = [entry]
        h_1 = None if entry.image is None else imagehash.average_hash(entry.image, 16)
        t1 = remove_special_characters(entry.title)
        idx_to_remove = set()
        for i, entry_2 in enumerate(entries_c):
            t2 = remove_special_characters(entry_2.title)
            is_same_title = t1 == t2
            if entry.image is None or entry_2.image is None:
                is_same = is_same_title and is_same_price
                if is_same:
                    group.append(entry_2)
                    idx_to_remove.add(i)
                continue
            h_2 = imagehash.average_hash(entry_2.image, 16)
            similarity_score = (h_1 - h_2) / h_1.hash.size
            if similarity_score < 0.1 or (is_same_title and is_same_price):
                group.append(entry_2)
                idx_to_remove.add(i)
        grouped_offers.append(group)
        entries_c = [entries_c[i] for i, _ in enumerate(entries_c) if i not in idx_to_remove]
    return grouped_offers


def lzx_entry_to_dict(entry: FeedParserDict):
    return dict(
        image=entry.href,
        link=entry.link,
        price=entry.summary,
        date=parse_date(entry.published),
        name=entry.title
    )


def pepper_entry_to_dict(entry: FeedParserDict):
    return dict(
        image=entry['media_content'][0]['url'],
        link=entry.link,
        price=entry.get('pepper_merchant', {}).get('price', None),
        date=parse_date(entry.published),
        name=entry.title
    )


def pepper_hottest_to_dict(offer: namedtuple) -> dict:
    return dict(
        image=offer.image,
        link=offer.href,
        price=None,
        date=None,
        name=offer.title
    )


def get_unique_offers(grouped_offers: list[list[FeedParserDict]]) -> list[dict]:
    unique_offers = [g[0] for g in grouped_offers if len(g) == 1]
    return [lzx_entry_to_dict(o) for o in unique_offers]


def get_duplicated_offers(grouped_offers: list[list[FeedParserDict]]) -> list[list[dict]]:
    duplicated_offers = [g for g in grouped_offers if len(g) > 1]

    def to_list_of_dicts(duplicates: list) -> list:
        return [lzx_entry_to_dict(o) for o in duplicates]

    return [to_list_of_dicts(duplicates) for duplicates in duplicated_offers]


def generate_html_str(unique_offers: list[dict], duplicated_offers: list[list[dict]]) -> str:
    with open('template.html', 'rt', encoding='utf-8') as f:
        html_template = f.read()
    template = Template(html_template)
    return template.render(
        individual_offers=unique_offers, duplicated_offers=duplicated_offers
    )


def send_mail(html_content: str) -> None:
    email_subject = 'Oferty LZX i Pepper'
    with open('secrets.yml', 'rt') as f:
        secrets = EasyDict(yaml.safe_load(f))
    yag = yagmail.SMTP(secrets.src_mail, secrets.src_pwd, port=587, smtp_starttls=True, smtp_ssl=False)
    yag.send(to=secrets.dst_mail, subject=email_subject, contents=(html_content, 'text/html'))


def get_driver() -> webdriver.Chrome:
    op = webdriver.ChromeOptions()
    op.add_argument("window-size=1600,1080")  # Specify resolution
    op.add_argument('--headless')
    op.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/2b7c7"
    )
    return webdriver.Chrome(service=Service(CHROME_DRIVER_PATH), options=op)


def click_element(wait: WebDriverWait, element):
    button = wait.until(EC.element_to_be_clickable(element))
    button.click()


def get_hottest_pepper_offers() -> set[namedtuple]:
    driver = get_driver()
    driver.get(URL)
    wait = WebDriverWait(driver, 20)
    click_element(wait, SKIP_COOKIES)

    pagination_buttons = wait.until(EC.presence_of_all_elements_located(HOTTEST_OFFERS_PAGES))

    all_hottest_offers = set()
    Offer = namedtuple('Offer', ['title', 'href', 'image'])
    for page_index in range(len(pagination_buttons)):
        # Refresh the list of pagination buttons
        pagination_buttons = wait.until(EC.presence_of_all_elements_located(HOTTEST_OFFERS_PAGES))
        if page_index > 0:
            pagination_buttons[page_index].click()

        items = wait.until(EC.presence_of_all_elements_located(HOTTEST_OFFERS))
        # Extract information from each item
        for item in items:
            link_element = item.find_element(By.TAG_NAME, "a")
            href = link_element.get_attribute("href")
            title = link_element.get_attribute("title")
            image_element = item.find_element(By.TAG_NAME, "img")
            image_src = image_element.get_attribute("src")

            all_hottest_offers.add(Offer(title, href, image_src))

    driver.close()
    return all_hottest_offers


def main():
    lzx_entries = get_last_day_entries(LZX_RSS_URL)
    lzx_entries = assign_direct_offers_links(lzx_entries)
    lzx_entries = assign_images_lzx(lzx_entries)
    grouped_entries = group_entries(lzx_entries)
    unique_offers = get_unique_offers(grouped_entries)
    duplicated_offers = get_duplicated_offers(grouped_entries)

    pepper_entries = get_last_day_entries(PEPPER_RSS_URL)
    pepper_entries = [pepper_entry_to_dict(entry) for entry in pepper_entries]
    unique_offers.extend(pepper_entries)

    hottest = get_hottest_pepper_offers()
    hottest = [pepper_hottest_to_dict(offer) for offer in hottest]
    unique_offers.extend(hottest)
    html_content = generate_html_str(unique_offers, duplicated_offers)
    # with open('test.html', 'w', encoding='utf-8-sig') as f:
    #     f.write(html_content)
    send_mail(html_content)


if __name__ == '__main__':
    logging.basicConfig(filename='error.log', level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
    schedule.every().day.at("11:05").do(main)
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logging.exception("An error occurred:")
        time.sleep(1)
    # main()
