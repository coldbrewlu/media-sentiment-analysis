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
        return None

    try:
        author, content = fetch_detail(art["link"])
    except Exception as e:
        logger.warning(f"Failed to fetch detail → {art['link']}: {e}")
        return None

    return {
        "url": art["link"],
        "title": art["title"],
        "date": article_date,
        "author": author,
        "content": content,
    }


# ——— MAIN SCRAPER —————————————————————————————————————
def scrape_all():
    conn = init_db()
    page = 10300

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
            logger.info("No articles within date threshold on page %d.", page)
            page += 1
            continue
        
        logger.info("Fetching %d articles in parallel...", len(articles_to_fetch))

        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(fetch_and_build, art) for art in articles_to_fetch]
            for future in tqdm(as_completed(futures), total=len(futures), desc=f"Page {page}", unit="art"):
                result = future.result()
                if result:
                    save_article(conn, result)

        page += 1
        time.sleep(DELAY)

    conn.close()
    logger.info("Scraping complete.")


if __name__ == "__main__":
    scrape_all()
