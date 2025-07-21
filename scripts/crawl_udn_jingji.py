# 经济日报
import os
import json
import time
import requests
from bs4 import BeautifulSoup

SAVE_DIR = "data/raw/udn"
BASE_URL = "https://money.udn.com"
LIST_URL = "https://money.udn.com/rank/newest/1001"

KEYWORDS = ["私营企业", "民营企业", "非公有制经济", "个体工商户"]
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_article_links():
    soup = BeautifulSoup(requests.get(LIST_URL, headers=HEADERS).text, "html.parser")
    links = [BASE_URL + a["href"] for a in soup.select("dt a[href]")]
    return links

def parse_article(url):
    soup = BeautifulSoup(requests.get(url, headers=HEADERS).text, "html.parser")
    title = soup.select_one("h1")
    content = soup.select_one("section.article-content__editor")

    if not title or not content:
        return None

    text = content.get_text(separator="\n").strip()
    if not any(k in text for k in KEYWORDS):
        return None

    return {
        "title": title.text.strip(),
        "url": url,
        "source": "经济日报（UDN）",
        "content": text
    }

def crawl_articles():
    os.makedirs(SAVE_DIR, exist_ok=True)
    links = fetch_article_links()
    results = []
    for url in links:
        print(f"🔗 {url}")
        article = parse_article(url)
        if article:
            results.append(article)
        time.sleep(0.5)
    with open(f"{SAVE_DIR}/udn_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    crawl_articles()
