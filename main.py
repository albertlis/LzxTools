import logging
import os
import platform
import time
import argparse
import zipfile
from pathlib import Path
from typing import Callable, Iterable

import schedule
import yagmail
from dotenv import load_dotenv
from jinja2 import Template

from lzx_parser import LzxScrapper
from otomoto_scrapper import OtomotoScrapper
from pepper_scrapper import PepperScrapper


def generate_html_str(unique_offers: list[dict], *, web: bool = False) -> str:
    """Render offers to HTML.

    Args:
        unique_offers: Normalized list of offer dicts.
        web: If True, use the full-featured web template (template_web.html)
             instead of the email-safe template.
    """
    from datetime import datetime
    template_file = 'template_web.html' if web else 'template.html'
    with open(template_file, 'rt', encoding='utf-8') as f:
        html_template = f.read()
    template = Template(html_template)
    return template.render(
        individual_offers=unique_offers,
        generated_at=datetime.now().strftime('%Y-%m-%d %H:%M'),
    )


def send_mail(html_content: str) -> None:
    email_subject = 'Oferty LZX i Pepper'
    yag = yagmail.SMTP(os.getenv('SRC_MAIL'), os.getenv('SRC_PWD'), port=587, smtp_starttls=True, smtp_ssl=False)

    content_bytes = html_content.encode('utf-8')
    content_size = len(content_bytes)
    logging.info(f"Preparing email. Content size: {content_size} bytes ({len(html_content)} chars)")

    # If content is large (> 100KB), send as attachment to avoid Gmail clipping/delivery issues
    # Gmail clips messages at ~102KB and may silently reject without SMTP error
    if content_size > 100_000:
        logging.warning(f"Content large ({content_size}). Sending as ZIP attachment.")
        html_path = 'offers_large.html'
        zip_path = 'offers_large.zip'

        # Write HTML file
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # Pack to ZIP with high compression
        with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
            zipf.write(html_path, arcname='offers.html')

        zip_size = os.path.getsize(zip_path)
        logging.info(f"Compressed {content_size} bytes to {zip_size} bytes ({100 * (1 - zip_size / content_size):.1f}% reduction)")

        result = yag.send(
            to=os.getenv('DST_MAIL'),
            subject=email_subject,
            contents="Wiadomość jest zbyt duża. Oferty znajdują się w załączniku ZIP.",
            attachments=[zip_path]
        )
        logging.info(f"Email send result (with ZIP attachment): {result}")

        try:
            os.remove(html_path)
            os.remove(zip_path)
        except OSError:
            pass
    else:
        # Send as plain HTML content without CSS processing
        result = yag.send(
            to=os.getenv('DST_MAIL'),
            subject=email_subject,
            contents=html_content,
            attachments=None
        )
        logging.info(f"Email send result (inline HTML): {result}")


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
        return scr.get_offers()
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
        logging.warning(f"Ignoring unknown sources: {', '.join(invalid)}")
    selected = [s for s in ("pepper", "lzx", "otomoto") if s in wanted]
    if not selected:
        logging.warning("No valid sources selected; defaulting to pepper.")
        return ["pepper"]
    return selected


def _aggregate_offers(sources: Iterable[str]) -> list[dict]:
    aggregated: list[dict] = []
    for src in sources:
        logging.info(f"Scraping: {src}")
        offers = SCRAPER_REGISTRY[src]()
        logging.info(f"Fetched {len(offers)} offers from {src}")
        # Tag each offer with its source so templates can filter/badge by it
        for o in offers:
            o.setdefault("source", src)
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
    logging.info(f"Total unique offers: {len(unique)}")
    return unique


NGINX_DEFAULT_PATH = "/var/www/oferty/index.html"


def publish_to_nginx(html_content: str, dest: str = NGINX_DEFAULT_PATH) -> None:
    """Write the rendered HTML directly to the nginx webroot.

    Args:
        html_content: Rendered HTML string.
        dest: Absolute path of the target file (default: /var/www/oferty/index.html).

    The parent directory is created if it does not exist.
    Writes are atomic: content is written to a .tmp sibling first and then
    renamed so nginx never serves a half-written file.
    """
    dest_path = Path(dest)
    tmp_path = dest_path.with_suffix(".tmp")
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(html_content, encoding="utf-8")
        tmp_path.replace(dest_path)
        logging.info(f"Published web view → {dest_path} ({len(html_content.encode())} bytes)")
    except OSError:
        logging.exception(f"Failed to write nginx output to {dest}")
        raise


def run_once(selected_sources: list[str], *, send_email: bool, nginx_dest: str | None = None) -> None:
    _nice_if_linux()
    _load_env()
    offers = _aggregate_offers(selected_sources)

    # Always write local test.html (email template)
    html_email = generate_html_str(offers, web=False)
    with open('test.html', 'w', encoding='utf-8-sig') as f:
        f.write(html_email)
    logging.info("Wrote test.html")

    if send_email:
        try:
            send_mail(html_email)
            logging.info("Email sent.")
        except Exception:
            logging.exception("Failed to send email")

    if nginx_dest is not None:
        html_web = generate_html_str(offers, web=True)
        with open('html_web.html', 'wt', encoding='utf-8') as f:
            f.write(html_web)
        publish_to_nginx(html_web, dest=nginx_dest)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Scrape selected sources and produce HTML/email.")
    p.add_argument("--sources", help="Comma separated: pepper,lzx,otomoto (default: pepper)")
    p.add_argument("--email", action="store_true", help="Send email with results")
    p.add_argument(
        "--nginx",
        metavar="PATH",
        nargs="?",
        const=NGINX_DEFAULT_PATH,
        default=None,
        help=(
            "Publish a beautiful web view via nginx. "
            f"Optional: path to output file (default: {NGINX_DEFAULT_PATH}). "
            "Example: --nginx or --nginx /var/www/oferty/index.html"
        ),
    )
    p.add_argument("--schedule", metavar="HH:MM", help="If set, run daily at given 24h time")
    p.add_argument("--once", action="store_true", help="Run once immediately (default if no --schedule)")
    p.add_argument(
        "--log-level",
        metavar="LEVEL",
        default="INFO",
        help="Logging level: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)"
    )
    return p


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    selected = _parse_sources(args.sources)
    nginx_dest: str | None = args.nginx

    # Configure logging with specified level
    log_level = getattr(logging, args.log_level.upper(), logging.INFO)
    logging.basicConfig(
        format='%(asctime)s - %(levelname)s - Line: %(lineno)d - %(filename)s - %(funcName)s() - %(message)s',
        level=log_level
    )
    logging.getLogger("selenium").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    if args.schedule:
        # Schedule daily run
        schedule.clear()
        schedule.every().day.at(args.schedule).do(
            run_once, selected_sources=selected, send_email=args.email, nginx_dest=nginx_dest
        )
        logging.info(f"Scheduled daily run at {args.schedule} for sources: {','.join(selected)}")
        # Also run immediately unless suppressed
        if not args.once:
            run_once(selected, send_email=args.email, nginx_dest=nginx_dest)
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
        run_once(selected, send_email=args.email, nginx_dest=nginx_dest)


if __name__ == '__main__':
    main()
