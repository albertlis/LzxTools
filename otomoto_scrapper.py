import logging
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from scrapper_base import ScrapperBase


@dataclass(frozen=True, slots=True)
class OtomotoOffer:
    title: str
    link: str
    year: str
    mileage: str
    image_link: str
    price: str


class OtomotoScrapper(ScrapperBase):
    def __init__(self, link: str):
        super().__init__(cache_path=Path('otomoto_cache.pkl.zstd'))
        self.link = link
        self.cache_path = "otomoto_cache.pkl.zstd"
        self.cache = self.load_cache()

    def get_offers(self) -> list[OtomotoOffer]:
        response = requests.get(self.link, headers=self.headers)
        new_offers = []
        # Check if the request was successful
        if response.status_code == 200:
            # Parse the HTML using BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')

            if search_results_div := soup.find('div', {'data-testid': 'search-results'}):
                # Find all the article elements inside the div
                articles = search_results_div.find_all(
                    'article', {'data-media-size': 'small', 'data-orientation': 'horizontal'}
                )
                for article in articles:
                    title_tag = article.find('h1')
                    link = title_tag.find('a')['href']
                    title = title_tag.get_text(strip=True)
                    logging.debug(f"Title: {title}, Link: {link}")

                    parameters = article.find_all('dd', {'data-parameter': True})
                    params = {}
                    for param in parameters:
                        parameter_type = param['data-parameter']
                        parameter_value = param.get_text(strip=True)
                        params[parameter_type] = parameter_value
                        logging.debug(f"{parameter_type.capitalize()}: {parameter_value}")

                    image_tag = article.find('img')
                    image_url = image_tag.get('src')
                    logging.debug(f"Image URL: {image_url}")

                    price = ''
                    for div in article.find_all('div'):
                        if price_tag := div.find('p', text=lambda text: text and 'PLN' in text):
                            h3 = div.find('h3')
                            if h3 is None:
                                continue
                            price = h3.get_text(strip=True)
                            break

                    if not price:
                        logging.error('Otomoto price not found')
                    offer = OtomotoOffer(title, link, params['year'], params['mileage'], image_url, price)
                    if offer not in self.cache:
                        new_offers.append(offer)
                        self.cache.add(offer)
                    logging.debug("-" * 40)  # separator between articles

            else:
                logging.warning('No Otomoto offers found')
        else:
            logging.error(f'Otomoto error when loading page. Status code: {response.status_code}')
        return new_offers

    def new_offers_to_dict(self, new_offers: list[OtomotoOffer]) -> list[dict[str, str]]:
        converted = []
        for offer in new_offers:
            dict_offer = dict(
                name=f'{offer.title}, {offer.year}, {offer.mileage}',
                image=offer.image_link,
                link=offer.link,
                price=offer.price,
            )
            converted.append(dict_offer)
        return converted
