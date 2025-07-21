import os
import re
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import date, timedelta

HEADERS = {"User-Agent": "Mozilla/5.0"}
KEYWORDS = ["私营企业", "民营企业", "非公有制经济", "个体工商户"]
SAVE_DIR = "data/raw"

BASE_URL = "https://data.people.com.cn"

def get_soup(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        res.encoding = res.apparent_encoding
        return BeautifulSoup(res.text, "html.parser")
    except Exception as e:
        print(f"Failed to fetch {url}: {e}")
        return None

def get_article_links(date_str):
    """
    Fetch all article links from the list page of a given date
    e.g. https://data.people.com.cn/rmrb/20250710/1?code=2
    """
    list_url = f"{BASE_URL}/rmrb/{date_str}/1?code=2"
    soup = get_soup(list_url)
    if not soup:
        return []

    links = []
    for a in soup.select("ol li a[href]"):
        href = a.get("href")
        full_url = urljoin(list_url, href)
        links.append(full_url)
    return links

def extract_article(article_url):
    soup = get_soup(article_url)
    if not soup:
        return None

    title_tag = soup.select_one("h3")
    content_div = soup.select_one("div.article-content")

    if not title_tag or not content_div:
        return None

    content = content_div.get_text(separator="\n").strip()
    if not any(keyword in content for keyword in KEYWORDS):
        return None

    date_match = re.search(r"/rmrb/(\d{8})/", article_url)
    date_str = date_match.group(1) if date_match else "unknown"

    return {
        "title": title_tag.get_text(strip=True),
        "url": article_url,
        "date": date_str,
        "source": "人民日报",
        "content": content
    }

def crawl_day(d: date):
    date_str = d.strftime("%Y%m%d")
    print(f"📅 Crawling: {date_str}")

    article_links = get_article_links(date_str)
    if not article_links:
        print("❌ No article links found.")
        return []

    results = []
    for url in article_links:
        print(f"🔗 {url}")
        article = extract_article(url)
        if article:
            results.append(article)
        time.sleep(0.5)
    return results

def save_articles(articles, date_str):
    os.makedirs(SAVE_DIR, exist_ok=True)
    path = os.path.join(SAVE_DIR, f"peopledata_{date_str}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
    print(f"✅ Saved {len(articles)} articles to {path}")

def date_range(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)

if __name__ == "__main__":
    # Crawl one day for testing
    start_date = date(1978, 1, 1)  # or earlier for real archive
    end_date = date(2021, 1, 1)

    for d in date_range(start_date, end_date):
        try:
            articles = crawl_day(d)
            if articles:
                save_articles(articles, d.strftime("%Y%m%d"))
        except Exception as e:
            print(f"⚠️ Error on {d}: {e}")
        time.sleep(1)
