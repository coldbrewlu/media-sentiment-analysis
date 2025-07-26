#!/usr/bin/env python3
"""
Recursive crawler for Renmin Ribao articles.

- Uses a PostgreSQL-backed queue to avoid in-memory explosion.
- Processes queue in batches of 20, fetching/parsing concurrently.
- Stores full article data for articles dated ≤ 2021-12-31, via execute_values.
- Seed mode (--seed) scrapes section homepages first.
"""

import os
import re
import sys
import time
import argparse
import logging
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import psycopg2
from psycopg2.extras import execute_values
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# ------------------------------------------------------------------------------
# Configuration & Logging
# ------------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

DB_DSN = (
    f"dbname={os.getenv('RENMINRIBAO_DB_NAME')}"
    f" user={os.getenv('DB_USER')}"
    f" password={os.getenv('DB_PASSWORD')}"
    f" host={os.getenv('DB_HOST')}"
    f" port={os.getenv('DB_PORT')}"
)

SECTION_HOMEPAGES = {
    "finance": "http://finance.people.com.cn/",
    "world": "http://world.people.com.cn/",
}

DATE_THRESHOLD = datetime.date(2021, 12, 31)
BATCH_SIZE = 20
MAX_WORKERS = 8
FETCH_TIMEOUT = 10

ARTICLE_PATH_RE = re.compile(r"^/n1/\d{4}/\d{4}/c\d+-\d+\.html")

# ------------------------------------------------------------------------------
# Utility Functions
# ------------------------------------------------------------------------------


def fetch_page(url: str, timeout: int = FETCH_TIMEOUT) -> str:
    try:
        resp = requests.get(url, timeout=timeout)
        resp.encoding = "utf-8"
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return ""


def url_base(url: str) -> str:
    parts = url.split("/")[:3]
    return "/".join(parts)


# ------------------------------------------------------------------------------
# HTML Parsers & Workers
# ------------------------------------------------------------------------------


def parse_homepage(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        if ARTICLE_PATH_RE.match(a["href"]):
            yield base_url.rstrip("/") + a["href"]


def extract_top10_ranking(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    div = soup.find("div", class_="rm_ranking")
    if not div:
        return []
    ul = div.find("ul", class_="rm_ranking_list")
    if not ul:
        return []
    return [base_url.rstrip("/") + li.a["href"] for li in ul.find_all("li") if li.a]


def extract_article_metadata(html: str, url: str, section: str):
    soup = BeautifulSoup(html, "html.parser")
    # Title
    title = (soup.find("h1") or BeautifulSoup("", "html.parser")).get_text(strip=True)
    # Date
    date = None
    m = re.search(r"/n1/(\d{4})/(\d{2})(\d{2})/", url)
    if m:
        year, mo, da = m.group(1), m.group(2), m.group(3)
        date = datetime.date(int(year), int(mo), int(da))
    # Author
    author = (
        soup.find("div", class_="author").get_text(" ", strip=True)
        if soup.find("div", class_="author")
        else ""
    )
    # Source
    sm = soup.find("meta", {"name": "source"})
    source = sm["content"] if sm and sm.get("content") else ""
    # Content
    paragraphs = soup.find("div", class_="rm_txt_con")
    content = ""
    if paragraphs:
        content = "\n\n".join(p.get_text(strip=True) for p in paragraphs.find_all("p"))
    return {
        "url": url,
        "title": title,
        "date": date,
        "author": author,
        "source": source,
        "content": content,
        "section": section,
    }


def worker_process(url: str):
    """
    Worker: fetch + parse one URL.
    Returns: (url, metadata_dict or None, [ranking_links])
    """
    logger.info(f"Examining: {url}")
    html = fetch_page(url)
    if not html:
        return url, None, []
    section = next(
        (sec for sec, hp in SECTION_HOMEPAGES.items() if url.startswith(hp)), ""
    )
    meta = extract_article_metadata(html, url, section)
    rankings = extract_top10_ranking(html, url_base(url))
    return url, meta, rankings


# ------------------------------------------------------------------------------
# Database Queue & Storage
# ------------------------------------------------------------------------------


class CrawlerDB:
    def __init__(self, dsn):
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = True

    def init_db(self):
        with self.conn.cursor() as cur:
            cur.execute(
                """
            CREATE TABLE IF NOT EXISTS crawl_queue (
                url TEXT PRIMARY KEY,
                enqueued_at TIMESTAMP DEFAULT now()
            );
            """
            )
            cur.execute(
                """
            CREATE TABLE IF NOT EXISTS examined_links (
                url TEXT PRIMARY KEY,
                examined_at TIMESTAMP DEFAULT now()
            );
            """
            )
            cur.execute(
                """
            CREATE TABLE IF NOT EXISTS articles (
                id SERIAL PRIMARY KEY,
                url TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                date DATE,
                author TEXT,
                source TEXT,
                content TEXT,
                section TEXT,
                scraped_at TIMESTAMP DEFAULT now()
            );
            """
            )
            logger.info("✅ Database tables checked/created.")

    def clear_tables(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM crawl_queue;")
            cur.execute("DELETE FROM examined_links;")
        logger.info("✅ Cleared both crawl_queue and examined_links tables.")

    def enqueue_if_new(self, url):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO crawl_queue (url) VALUES (%s) ON CONFLICT DO NOTHING",
                (url,),
            )

    def fetch_queue_batch(self, limit=BATCH_SIZE):
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT url FROM crawl_queue ORDER BY enqueued_at ASC LIMIT %s",
                (limit,),
            )
            return [r[0] for r in cur.fetchall()]

    def delete_from_queue(self, url):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM crawl_queue WHERE url = %s", (url,))

    def already_examined(self, url):
        with self.conn.cursor() as cur:
            cur.execute("SELECT 1 FROM examined_links WHERE url = %s", (url,))
            return cur.fetchone() is not None

    def log_examined(self, url):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO examined_links (url) VALUES (%s) ON CONFLICT DO NOTHING",
                (url,),
            )

    def store_articles_bulk(self, metas):
        if not metas:
            return
        sql = """
          INSERT INTO articles
            (url, title, date, author, source, content, section)
          VALUES %s
          ON CONFLICT DO NOTHING
        """
        values = [
            (
                m["url"],
                m["title"],
                m["date"],
                m["author"],
                m["source"],
                m["content"],
                m["section"],
            )
            for m in metas
        ]
        with self.conn.cursor() as cur:
            execute_values(cur, sql, values)


# ------------------------------------------------------------------------------
# Main Crawler Logic
# ------------------------------------------------------------------------------


def run_crawler(db: CrawlerDB, seed: bool):
    if seed:
        logger.info("Seeding queue from section homepages...")
        for section, homepage in SECTION_HOMEPAGES.items():
            logger.info(f"Scraping homepage: {homepage} ({section})")
            html = fetch_page(homepage)
            for link in parse_homepage(html, url_base(homepage)):
                db.enqueue_if_new(link)
        logger.info("Seeding complete.")

    while True:
        batch = db.fetch_queue_batch()
        if not batch:
            logger.info("Crawl queue empty; exiting.")
            break

        metas_to_store = []
        new_links = set()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {executor.submit(worker_process, url): url for url in batch}
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    url, meta, rankings = future.result()
                    db.log_examined(url)
                    if meta and meta["date"]:
                        if meta["date"] <= DATE_THRESHOLD:
                            metas_to_store.append(meta)
                            logger.info(f"Queued for storage: {url} ({meta['date']})")
                        else:
                            logger.info(
                                f"Skipped storage: article date {meta['date']} "
                                f"is after threshold {DATE_THRESHOLD}: {url}"
                            )
                    else:
                        logger.info(f"Skipped storage: no publish date found for {url}")
                    for r in rankings:
                        if not db.already_examined(r):
                            new_links.add(r)
                        else:
                            logger.info(f"Skipped storage: {url} is already examined.")
                except Exception as e:
                    logger.error(f"Worker error on {url}: {e}")
                finally:
                    db.delete_from_queue(url)

        # batch‐insert articles
        db.store_articles_bulk(metas_to_store)
        # enqueue newly discovered links
        for link in new_links:
            db.enqueue_if_new(link)

        time.sleep(1)  # polite pause


# ------------------------------------------------------------------------------
# CLI Entry Point
# ------------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Renmin Ribao recursive crawler")
    parser.add_argument(
        "--seed",
        action="store_true",
        help="If set, scrape section homepages first to seed the queue",
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="If set, delete all records from crawl_queue and examined_links, then exit"
    )
    args = parser.parse_args()

    try:
        db = CrawlerDB(DB_DSN)
        db.init_db()
    except Exception as e:
        logger.error(f"DB connection failed: {e}")
        sys.exit(1)
        
    if args.clear:
        db.clear_tables()
        sys.exit(0)

    run_crawler(db, seed=args.seed)
