import os
import logging
import psycopg2
from psycopg2.extras import execute_values
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from ..const.util import is_relevant_article

load_dotenv()

MAX_WORKERS = 8   # tune this: more threads for I/O-heavy; for CPU-heavy, try cpu_count()


# ——— DB CONFIG ———————————————————————————————————————————————
DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT", 5432)),
    "dbname": os.getenv("DB_NAME"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
}

# ——— SOURCE DETECTION ——————————————————————————————————————————
def detect_source(url: str) -> str:
    u = url.lower()
    if "jingjiribao" in u:
        return "JingJiRiBao"
    if "gmrb" in u or "guangming" in u or "gmw.cn" in u:
        return "GuangMingRiBao"
    return "Unknown"

# ——— DDL ——————————————————————————————————————————————————
CREATE_RELEVANT_TABLE = """
CREATE TABLE IF NOT EXISTS relevant_articles (
    id               SERIAL PRIMARY KEY,
    old_article_id   INTEGER   NOT NULL UNIQUE
                       REFERENCES articles(id)
                       ON DELETE CASCADE,
    url              TEXT      NOT NULL,
    title            TEXT,
    date             DATE,
    author           TEXT,
    content          TEXT,
    source           TEXT      NOT NULL,
    transferred_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_PROGRESS_TABLE = """
CREATE TABLE IF NOT EXISTS transfer_progress (
    script_name      TEXT    PRIMARY KEY,
    last_processed   INTEGER NOT NULL,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

UPSERT_PROGRESS = """
INSERT INTO transfer_progress (script_name, last_processed)
VALUES (%s, %s)
ON CONFLICT (script_name)
  DO UPDATE SET last_processed = EXCLUDED.last_processed,
                updated_at = CURRENT_TIMESTAMP;
"""

GET_PROGRESS = """
SELECT last_processed
  FROM transfer_progress
 WHERE script_name = %s;
"""

# ——— SETTINGS ————————————————————————————————————————————————
BATCH_SIZE = 10000
SCRIPT_NAME = "relevant_transfer"

# ——— CONNECTION / INIT ——————————————————————————————————————
def get_conn():
    logger.info("Opening database connection")
    return psycopg2.connect(**DB_CONFIG)

def init_tables(conn):
    logger.info("Step 1: Ensuring tables exist")
    with conn.cursor() as cur:
        logger.debug(" - Creating relevant_articles table if needed")
        cur.execute(CREATE_RELEVANT_TABLE)
        logger.debug(" - Creating transfer_progress table if needed")
        cur.execute(CREATE_PROGRESS_TABLE)
    conn.commit()
    logger.info("Tables are ready")

# ——— PROGRESS —————————————————————————————————————————————
def get_last_id(conn):
    logger.info(f"Step 2: Loading last processed ID for '{SCRIPT_NAME}'")
    with conn.cursor() as cur:
        cur.execute(GET_PROGRESS, (SCRIPT_NAME,))
        row = cur.fetchone()
    last = row[0] if row else 0
    logger.info(f"Resuming from article ID {last}")
    return last

def upsert_progress(conn, last_id):
    logger.info(f"Updating progress: setting last_processed = {last_id}")
    with conn.cursor() as cur:
        cur.execute(UPSERT_PROGRESS, (SCRIPT_NAME, last_id))
    conn.commit()
    logger.info("Progress table updated")

# ——— FETCH & TRANSFER —————————————————————————————————————
def fetch_batch(conn, last_id):
    logger.info(f"Step 3: Fetching up to {BATCH_SIZE} articles with id > {last_id}")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, url, title, date, author, content
              FROM articles
             WHERE id > %s
             ORDER BY id
             LIMIT %s;
        """, (last_id, BATCH_SIZE))
        rows = cur.fetchall()
    if rows:
        logger.info(f"Fetched {len(rows)} articles (IDs {rows[0][0]}–{rows[-1][0]})")
    else:
        logger.info("No more articles found")
    return rows


def process_article(record):
    """
    record = (old_id, url, title, date_, author, content)
    Returns a 7-tuple (old_id, url, title, date_, author, content, source)
    or None if not relevant or on error.
    """
    old_id, url, title, date_, author, content = record
    try:
        if content and is_relevant_article(content):
            src = detect_source(url)
            logger.debug(f"[Thread] id={old_id} relevant → source={src}")
            return (old_id, url, title, date_, author, content, src)
        else:
            logger.debug(f"[Thread] id={old_id} not relevant")
    except Exception as e:
        logger.exception(f"[Thread] error at id={old_id}: {e}")
    return None

def transfer_batch(conn, batch):
    logger.info(f"Step 4: Parallel checking of {len(batch)} articles")
    to_insert = []

    # 1) spin up the pool
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        futures = {exe.submit(process_article, rec): rec for rec in batch}

        # 2) as each finishes, collect the “not-None” results
        for fut in as_completed(futures):
            result = fut.result()
            if result:
                to_insert.append(result)

    logger.info(f"  → {len(to_insert)} articles matched relevance in this batch")

    # 3) bulk-insert them all in one go
    if to_insert:
        with conn.cursor() as cur:
            execute_values(cur,
                """
                INSERT INTO relevant_articles
                  (old_article_id, url, title, date, author, content, source)
                VALUES %s
                ON CONFLICT (old_article_id) DO NOTHING;
                """,
                to_insert
            )
        conn.commit()
        logger.info("  → Inserted into relevant_articles")
    else:
        logger.info("  → No inserts needed for this batch")


def run():
    conn = get_conn()
    try:
        init_tables(conn)
        last_id = get_last_id(conn)

        while True:
            batch = fetch_batch(conn, last_id)
            if not batch:
                logger.info("All done! No further batches.")
                break

            transfer_batch(conn, batch)

            last_id = batch[-1][0]
            upsert_progress(conn, last_id)

    except Exception as e:
        logger.exception(f"Fatal error in run(): {e}")
    finally:
        logger.info("Closing database connection")
        conn.close()

if __name__ == "__main__":
    # ——— Logging setup —————————————————————————————————————————
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    # If you want even more detail, uncomment the next line:
    # logging.getLogger().setLevel(logging.DEBUG)
    logger = logging.getLogger(__name__)

    logger.info("=== Starting relevant-transfer script ===")
    run()
    logger.info("=== Script finished ===")
