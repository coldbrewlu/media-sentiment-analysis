import os
import time
import logging
import re
import requests
import psycopg2
import os
import random
from psycopg2 import sql
from bs4 import BeautifulSoup
from tqdm import tqdm
from dotenv import load_dotenv
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import psycopg2.extras as extras
from ..const.util import is_relevant_article

load_dotenv()

# ——— CONFIG —————————————————————————————————————————————
BASE_URL = "https://www.jingjiribao.cn/"
PAGE_PARAM = "?pageNumber="
HEADERS = {"User-Agent": "Mozilla/5.0"}
DATE_THRESHOLD = "2021-12-31"  # inclusive
DELAY = 1.0  # seconds between requests

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

# ——— LOGGING SETUP ——————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ——— DATABASE HELPERS ———————————————————————————————————
def init_db():
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
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM articles WHERE url = %s", (url,))
        return cur.fetchone() is not None


def save_article(conn, rec):
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

# ——— SCRAPING HELPERS ———————————————————————————————————
def extract_list_articles(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for li in soup.select("ul.data-list > li"):
        h3 = li.find("h3")
        if not h3 or not (a := h3.find("a")):
            continue
        title = a.get_text(strip=True)
        link = a["href"].strip()
        if link.startswith("/"):
            link = BASE_URL.rstrip("/") + link

        # extract YYYY-MM-DD
        date = None
        if sub := li.find("p", class_="subinfo"):
            if m := re.search(r"\b(\d{4}-\d{2}-\d{2})\b", sub.get_text()):
                date = m.group(1)

        out.append({"title": title, "link": link, "date": date})
    return out


def fetch_detail(url):
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    author = soup.select_one("span.authors")
    author = author.get_text(strip=True) if author else None

    paras = [
        p.get_text(strip=True)
        for p in soup.select("div.news-content p")
        if p.get_text(strip=True)
    ]
    content = "\n\n".join(paras)
    return author, content


def fetch_and_build(art):
    """Fetch detail page and return article record dict"""
    time.sleep(random.uniform(0.5, 1.2))
    try:
        article_date = datetime.strptime(art["date"], "%Y-%m-%d").date()
    except ValueError:
        logger.warning(f"Skipping malformed date: {art['date']} → {art['link']}")
        return False, None

    try:
        author, content = fetch_detail(art["link"])
        if not content: 
            return (False, None)
        if content and not is_relevant_article(content):
            logger.debug("Article not relevant → %s", art["link"])
            return (False, None)
    except Exception as e:
        logger.warning(f"Failed to fetch detail → {art['link']}: {e}")
        return False, None

    return (
        True,
        {
            "url": art["link"],
            "title": art["title"],
            "date": article_date,
            "author": author,
            "content": content,
        },
    )


# ——— MAIN SCRAPER —————————————————————————————————————
def scrape_all():
    conn = init_db()
    page = 23836

    while True:
        list_url = f"{BASE_URL}{PAGE_PARAM}{page}"
        logger.info("Loading list page %d → %s", page, list_url)
        r = requests.get(list_url, headers=HEADERS)
        r.encoding = "utf-8"
        r.raise_for_status()

        articles = extract_list_articles(r.text)

        # Filter first to avoid wasteful threads
        articles_to_fetch = []
        for art in articles:
            if not art["date"]:
                continue
            if art["date"] > DATE_THRESHOLD:
                continue
            if article_exists(conn, art["link"]):
                logger.debug("Already exists → %s", art["link"])
                continue
            articles_to_fetch.append(art)

        if not articles:
            logger.info("No articles found on page %d; stopping.", page)
            break
        if not articles_to_fetch:
            logger.info("No articles to fetch on page %d.", page)
            page += 1
            continue

        logger.info("Fetching %d articles in parallel...", len(articles_to_fetch))

        articles_to_save = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                executor.submit(fetch_and_build, art) for art in articles_to_fetch
            ]
            for future in tqdm(
                as_completed(futures),
                total=len(futures),
                desc=f"Page {page}",
                unit="art",
            ):
                is_relevant, result = future.result()
                if is_relevant and result:
                    # save_article(conn, result)
                    articles_to_save.append(result)
        
        if articles_to_save:
            save_articles_batch(conn, articles_to_save)
            logger.info("Saved %d articles from page %d", len(articles_to_save), page)

        page += 1
        time.sleep(DELAY)

    conn.close()
    logger.info("Scraping complete.")


if __name__ == "__main__":
    scrape_all()
