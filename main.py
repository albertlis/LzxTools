import logging
import os
import platform
import time
import argparse
from typing import Callable, Iterable

import schedule
import yagmail
from dotenv import load_dotenv
from jinja2 import Template

from lzx_parser import LzxScrapper
from otomoto_scrapper import OtomotoScrapper
from pepper_scrapper import PepperScrapper


def generate_html_str(unique_offers: list[dict]) -> str:
    with open('template.html', 'rt', encoding='utf-8') as f:
        html_template = f.read()
    template = Template(html_template)
    return template.render(
        individual_offers=unique_offers
    )


def send_mail(html_content: str) -> None:
    email_subject = 'Oferty LZX i Pepper'
    yag = yagmail.SMTP(os.getenv('SRC_MAIL'), os.getenv('SRC_PWD'), port=587, smtp_starttls=True, smtp_ssl=False)
    yag.send(to=os.getenv('DST_MAIL'), subject=email_subject, contents=(html_content, 'text/html'))


# -------- New helpers (senior-style refactor) --------

def _nice_if_linux() -> None:
    if platform.system() == "Linux":
        try:
            os.nice(10)
        except Exception:
            logging.debug("Could not adjust niceness", exc_info=True)


def _load_env() -> None:
    load_dotenv()
    # Only LZX URL is strictly needed when scraping lzx
    # (Do not raise if not selected later)
    # Extend validation easily here if required.


def _scrape_lzx() -> list[dict]:
    url = os.getenv('LZX_RSS_URL')
    if not url:
        logging.warning("LZX selected but LZX_RSS_URL not set; skipping.")
        return []
    try:
        scr = LzxScrapper(url)
        entries = scr.get_offers()
        return entries if isinstance(entries, list) else []
    except Exception:
        logging.exception("LZX scraping failed")
        return []


def _scrape_pepper() -> list[dict]:
    try:
        scr = PepperScrapper()
        offers = scr.get_hottest_pepper_offers()
        return scr.new_offers_to_dict(offers)
    except Exception:
        logging.exception("Pepper scraping failed")
        return []


def _scrape_otomoto() -> list[dict]:
    try:
        scr = OtomotoScrapper()
        offers = scr.get_offers()
        return offers if isinstance(offers, list) else []
    except Exception:
        logging.exception("Otomoto scraping failed")
        return []


SCRAPER_REGISTRY: dict[str, Callable[[], list[dict]]] = {
    "pepper": _scrape_pepper,
    "lzx": _scrape_lzx,
    "otomoto": _scrape_otomoto,
}


def _parse_sources(raw: str | None) -> list[str]:
    if not raw:
        return ["pepper"]  # previous implicit behavior
    wanted = {s.strip().lower() for s in raw.split(",") if s.strip()}
    if invalid := [w for w in wanted if w not in SCRAPER_REGISTRY]:
        logging.warning("Ignoring unknown sources: %s", ", ".join(invalid))
    selected = [s for s in ("pepper", "lzx", "otomoto") if s in wanted]
    if not selected:
        logging.warning("No valid sources selected; defaulting to pepper.")
        return ["pepper"]
    return selected


def _aggregate_offers(sources: Iterable[str]) -> list[dict]:
    aggregated: list[dict] = []
    for src in sources:
        logging.info("Scraping: %s", src)
        offers = SCRAPER_REGISTRY[src]()
        logging.info("Fetched %d offers from %s", len(offers), src)
        aggregated.extend(offers)
    # De-duplicate by a common key if available
    seen = set()
    unique: list[dict] = []
    for o in aggregated:
        if key := o.get("id") or o.get("url") or o.get("link"):
            if key in seen:
                continue
            seen.add(key)
        unique.append(o)
    logging.info("Total unique offers: %d", len(unique))
    return unique


def run_once(selected_sources: list[str], *, send_email: bool) -> None:
    _nice_if_linux()
    _load_env()
    offers = _aggregate_offers(selected_sources)
    html_content = generate_html_str(offers)
    with open('test.html', 'w', encoding='utf-8-sig') as f:
        f.write(html_content)
    logging.info("Wrote test.html")
    if send_email:
        try:
            send_mail(html_content)
            logging.info("Email sent.")
        except Exception:
            logging.exception("Failed to send email")


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scrape selected sources and produce HTML/email.")
    p.add_argument("--sources", help="Comma separated: pepper,lzx,otomoto (default: pepper)")
    p.add_argument("--email", action="store_true", help="Send email with results")
    p.add_argument("--schedule", metavar="HH:MM", help="If set, run daily at given 24h time")
    p.add_argument("--once", action="store_true", help="Run once immediately (default if no --schedule)")
    return p


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    selected = _parse_sources(args.sources)

    if args.schedule:
        # Schedule daily run
        schedule.clear()
        schedule.every().day.at(args.schedule).do(run_once, selected_sources=selected, send_email=args.email)
        logging.info("Scheduled daily run at %s for sources: %s", args.schedule, ",".join(selected))
        # Also run immediately unless suppressed
        if not args.once:
            run_once(selected, send_email=args.email)
        errors = 0
        while True:
            try:
                schedule.run_pending()
                time.sleep(10)
            except KeyboardInterrupt:
                logging.info("Interrupted by user.")
                break
            except Exception:
                logging.exception("Loop error")
                errors += 1
                if errors > 10:
                    logging.error("Too many errors; exiting.")
                    break
    else:
        run_once(selected, send_email=args.email)


if __name__ == '__main__':
    logging.basicConfig(
        format='%(asctime)s - %(levelname)s - Line: %(lineno)d - %(filename)s - %(funcName)s() - %(message)s',
        level=logging.INFO
    )
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    main()
