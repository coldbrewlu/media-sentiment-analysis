#!/usr/bin/env python3
import os
import time
import logging
import random
import html
import requests

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
from psycopg2 import extras

# your relevance checker
from ..const.util import is_relevant_article

# ——— CONFIG ——————————————————————————————————————————————————
load_dotenv()
DB_CONFIG = {
    "host":     os.getenv("DB_HOST"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME"),
    "user":     os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}
WORKERS     = 8
RETRY_DELAY = (0.5, 1.2)   # seconds uniform sleep between fetches
BATCH_SIZE  = 1000         # process 1000 rows at a time

# ——— LOGGING —————————————————————————————————————————————————
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ——— DB HELPERS ——————————————————————————————————————————————
def get_connection():
    return psycopg2.connect(**DB_CONFIG)

def batch_update_articles(conn, records):
    """
    Batch-update author/content for a list of (id, author, content) tuples
    using a single UPDATE ... FROM (VALUES ...) statement.
    """
    if not records:
        return

    values = [(rid, author, content) for rid, author, content in records]
    sql = """
    UPDATE articles AS a
       SET author     = v.author
         , content    = v.content
         , scraped_at = CURRENT_TIMESTAMP
    FROM (VALUES %s) AS v(id, author, content)
    WHERE a.id = v.id
    """

    with conn.cursor() as cur:
        extras.execute_values(
            cur,
            sql,
            values,
            template="(%s, %s, %s)",
            page_size=BATCH_SIZE,
        )
    conn.commit()
    logger.info("Batch-updated %d articles", len(records))

# ——— FETCH & PARSE ——————————————————————————————————————————
def get_source(url: str) -> str:
    if "jingjiribao.cn" in url:
        return "jingji"
    if "gmrb" in url:
        return "gmrb"
    return "unknown"

def fetch_and_process(record):
    """
    Fetch detail page for (id, url) → return (id, author, content)
    or None on skip/failure.
    """
    rid, url = record
    time.sleep(random.uniform(*RETRY_DELAY))

    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"[{rid}] HTTP error: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    source = get_source(url)

    # select the correct container and author logic per source
    if source == "jingji":
        container = soup.select_one("div.news-content#news-content")
    elif source == "gmrb":
        container = soup.select_one("div#articleContent") or soup.select_one("div.news-content")
    else:
        logger.warning(f"[{rid}] Unknown source, skipping: {url}")
        return None

    if not container:
        logger.warning(f"[{rid}] Missing content container on {source} page")
        return None

    # unescape and re-parse HTML
    raw = container.decode_contents()
    decoded = html.unescape(raw)
    inner = BeautifulSoup(decoded, "html.parser")
    # print(f"Raw: {raw}")
    # print(f"Decoded: {decoded}")

    paras = [p.get_text(strip=True) for p in inner.find_all("p") if p.get_text(strip=True)]
    content = "\n\n".join(paras)
    if not content:
        logger.info(f"[{rid}] Empty content after parsing, skipping")
        return None

    if not is_relevant_article(content):
        logger.debug(f"[{rid}] Not relevant, skipping")
        return None

    # extract author differently per source
    if source == "jingji":
        # <span class="authors" id="news-authors">...</span>
        author_tag = soup.select_one("span.authors#news-authors") or soup.select_one("span.authors")
        author = author_tag.get_text(strip=True) if author_tag else None
    else:  # gmrb
        # <div class="lai"><span>作者：本报记者 Name</span></div>
        lai = soup.select_one("div.lai span")
        if lai:
            text = lai.get_text(strip=True)
            author = text.split("：", 1)[-1].strip()
        else:
            author = None

    return (rid, author, content)

# ——— MAIN WORKFLOW ——————————————————————————————————————————
def main():
    conn = get_connection()
    # use a server-side cursor to page through 40k+ rows without loading all at once
    cur = conn.cursor(name="empty_cursor")
    cur.itersize = BATCH_SIZE
    cur.execute("""
        SELECT id, url
          FROM articles
         WHERE content IS NULL OR content = ''
         ORDER BY id
    """)

    total_updated = 0
    while True:
        batch = cur.fetchmany(BATCH_SIZE)
        if not batch:
            break

        results = []
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(fetch_and_process, rec): rec for rec in batch}
            for fut in as_completed(futures):
                rec = futures[fut]
                try:
                    out = fut.result()
                except Exception as e:
                    logger.error(f"[{rec[0]}] Unexpected error: {e}", exc_info=True)
                    continue
                if out:
                    results.append(out)

        if results:
            batch_update_articles(conn, results)
            total_updated += len(results)

        logger.info(f"Batch complete: processed {len(batch)}, updated {len(results)}, total updated {total_updated}")

    cur.close()
    conn.close()
    logger.info(f"All done. Total articles updated: {total_updated}")

if __name__ == "__main__":
    main()
