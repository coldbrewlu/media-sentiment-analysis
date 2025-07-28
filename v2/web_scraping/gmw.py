import os
import time
import logging
import requests
import html
import psycopg2
from tqdm import tqdm
import random
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import psycopg2.extras as extras
from dotenv import load_dotenv
from ..const.util import is_relevant_article

load_dotenv()

# ——— CONFIGURATION —————————————————————————————————————————————
BASE_URL = "https://epaper.gmw.cn/gmrb/html/"
HEADERS = {"User-Agent": "Mozilla/5.0"}
DATE_THRESHOLD = "2021-12-31"  # only scrape dates ≤ this cutoff
MAX_WORKERS = 16  # number of threads for parallel fetching
DELAY = 1.0  # pause between days to be polite

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

# ——— LOGGING SETUP ———————————————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gmrb")


# ——— DATABASE HELPERS ————————————————————————————————————————————
def init_db():
    """Open a psycopg2 connection using our env-driven settings."""
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            """
          CREATE TABLE IF NOT EXISTS articles (
            id          SERIAL PRIMARY KEY,
            url         TEXT    NOT NULL UNIQUE,
            title       TEXT,
            date        DATE,
            author      TEXT,
            content     TEXT,
            scraped_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
          );
        """
        )
    logger.info("Ensured articles table exists")
    return conn

def article_exists(conn, url):
    """Return True if this URL is already in our shared 'articles' table."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM articles WHERE url = %s", (url,))
        return cur.fetchone() is not None


def save_article(conn, rec):
    """
    Insert a new article record.
    ON CONFLICT DO NOTHING ensures idempotency across runs.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO articles (url, title, date, author, content)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
            """,
            (rec["url"], rec["title"], rec["date"], rec["author"], rec["content"]),
        )
    logger.info("Saved → %s", rec["url"])
    
def save_articles_batch(conn, records):
    if not records:
        return

    tuples = [(r['url'], r['title'], r['date'], r['author'], r['content']) for r in records]
    sql = """
        INSERT INTO articles (url, title, date, author, content)
        VALUES %s
        ON CONFLICT (url) DO NOTHING
    """
    try:
        with conn.cursor() as cur:
            # cap the page_size to avoid too-large queries
            page_size = min(len(records), 1000)
            extras.execute_values(cur, sql, tuples, page_size=page_size)
        logger.info("Batch-saved %d articles", len(records))
    except Exception as e:
        logger.error("Failed to batch-insert %d records: %s", len(records), e)
        # Optional: retry in smaller chunks here…



# ——— SCRAPING FUNCTIONS ————————————————————————————————————————
def get_sections_for_date(date_str):
    """
    1) Build the front-page URL for 第01版 on the given date
    2) Parse out each section link (e.g. 第02版, 第03版, …)
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    url = f"{BASE_URL}{dt.year}-{dt.month:02d}/{dt.day:02d}/nbs.D110000gmrb_01.htm"
    r = requests.get(url, headers=HEADERS)
    r.encoding = "utf-8"
    r.raise_for_status()

    decoded_html = html.unescape(r.text)
    soup = BeautifulSoup(decoded_html, "html.parser")
    sections = []
    for a in soup.select("div.list_r ul li a#pageLink"):
        title = a.get_text(strip=True)
        href = a["href"]
        full = urljoin(url, href)
        sections.append((title, full))
    return sections


def get_articles_in_section(section_url):
    """
    Given a section page (e.g. 第02版), extract every article title + URL.
    """
    r = requests.get(section_url, headers=HEADERS)
    r.encoding = "utf-8"
    r.raise_for_status()

    decoded_html = html.unescape(r.text)
    soup = BeautifulSoup(decoded_html, "html.parser")
    articles = []
    for a in soup.select("div.list_l ul li a"):
        title = a.get_text(strip=True)
        href = a["href"]
        full = urljoin(section_url, href)
        articles.append((title, full))
    return articles


def fetch_article_detail(url):
    """
    1) Pull the detail page
    2) Extract the author from <div class="lai"><span>…
    3) Concatenate all <p> inside #articleContent into a single passage
    """
    r = requests.get(url, headers=HEADERS)
    r.encoding = "utf-8"
    r.raise_for_status()

    decoded_html = html.unescape(r.text)
    soup = BeautifulSoup(decoded_html, "html.parser")
    author_tag = soup.select_one("div.lai span")
    author = author_tag.get_text(strip=True).split("：", 1)[-1] if author_tag else None

    content_div = soup.find(id="articleContent")
    paras = content_div.find_all("p") if content_div else []
    texts = [p.get_text(strip=True) for p in paras if p.get_text(strip=True)]
    passage = "\n\n".join(texts)
    return author, passage

def fetch_section(sec):
    sec_title, sec_url = sec
    try:
        arts = get_articles_in_section(sec_url)
        # tag each article with its section title
        return [(sec_title, title, url) for title, url in arts]
    except Exception as e:
        logger.warning("Error fetching %s: %s", sec_url, e)
        return []

def filter_new_urls(conn, candidates):
    """
    Given a list of (sec_title, art_title, art_url),
    return only those whose art_url is *not* already in articles.
    """
    urls = [art_url for *_ , art_url in candidates]
    if not urls:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT url FROM articles WHERE url = ANY(%s)",
            (urls,)
        )
        existing = {row[0] for row in cur.fetchall()}

    return [trip for trip in candidates if trip[2] not in existing]


def build_article_record(date_str, section_title, art_title, art_url):
    """
    Wrapper for parallel executor:
    returns a dict matching our DB schema, or None on failure.
    """
    time.sleep(random.uniform(0.5, 1.2))  # be polite with delays
    try:
        author, content = fetch_article_detail(art_url)
        if not content:
            return False, None
        if content and not is_relevant_article(content):
            logger.debug("Article not relevant → %s", art_url)
            return (False, None)

    except Exception as e:
        logger.warning("Failed to fetch %s: %s", art_url, e)
        return None, None

    return True, {
        "url": art_url,
        "title": f"{section_title} | {art_title}",
        "date": datetime.strptime(date_str, "%Y-%m-%d").date(),
        "author": author,
        "content": content,
    }


# ——— MAIN SCRAPING LOOP ——————————————————————————————————————————
def date_range(start, end):
    """Yield each date from start through end (inclusive)."""
    delta = (end - start).days
    for i in range(delta + 1):
        yield start + timedelta(days=i)


def scrape_range(start_date: str, end_date: str):
    """Orchestrate scraping across the requested calendar range."""
    conn = init_db()
    d0 = datetime.strptime(start_date, "%Y-%m-%d").date()
    d1 = datetime.strptime(end_date, "%Y-%m-%d").date()

    for day in date_range(d0, d1):
        # skip any day beyond our threshold
        if str(day) > DATE_THRESHOLD:
            continue

        logger.info("=== Scraping %s ===", day)
        try:
            sections = get_sections_for_date(str(day))
        except Exception as e:
            logger.warning("Cannot load front page %s: %s", day, e)
            continue

        # gather every article that isn’t already in DB
        pending = []
        all_articles = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(fetch_section, sec) for sec in sections]
            for fut in as_completed(futures):
                all_articles.extend(fut.result())

        # 2) bulk‐filter by existing URLs
        pending = filter_new_urls(conn, all_articles)
        logger.info("Found %d new articles for %s", len(pending), day)
        total = len(pending)
        saved = 0
        
        articles_to_save = []
        # fetch details in parallel
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [
                pool.submit(build_article_record, str(day), sec, tit, url)
                for (sec, tit, url) in pending
            ]
            for fut in tqdm(
                as_completed(futures), total=total, desc=f"Processing {day}", unit="art"
            ):
                is_relevant, rec = fut.result()
                if is_relevant and rec:
                    # save_article(conn, rec)
                    articles_to_save.append(rec)
                    saved += 1
                    
        if articles_to_save:
            save_articles_batch(conn, articles_to_save)        

        logger.info("→ Saved %d/%d articles for %s", saved, total, day)

        # be polite
        time.sleep(DELAY)

    conn.close()
    logger.info("All done.")


if __name__ == "__main__":
    # adjust your desired window here:
    scrape_range("2016-04-10", "2021-12-31")
