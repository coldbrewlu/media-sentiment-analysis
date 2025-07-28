import logging
import re
import sys
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------

# List of homepage URLs to scrape
HOMEPAGE_URLS = [
    'http://finance.people.com.cn/',
    'http://world.people.com.cn/',
    # 'http://society.people.com.cn/',
    # 'http://kpzg.people.com.cn/',
    # 'http://edu.people.com.cn/'
]

# Regex to identify article links of the form '/n1/YYYY/MMDD/cXXXX-XXXXXX.html'
ARTICLE_PATH_RE = re.compile(r'^/n1/\d{4}/\d{4}/c\d+-\d+\.html')

# ------------------------------------------------------------------------------
# Logging Setup
# ------------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)-8s %(message)s'))
logger.addHandler(handler)

# ------------------------------------------------------------------------------
# Fetching and Parsing
# ------------------------------------------------------------------------------

def fetch_page(url: str, timeout: int = 10) -> Optional[str]:
    """
    Fetch the raw HTML of a page.
    Returns HTML text, or None if there was an error.
    """
    try:
        resp = requests.get(url, timeout=timeout)
        resp.encoding = 'utf-8'
        resp.raise_for_status()
        logger.info(f"Fetched {url}")
        return resp.text
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        return None

def parse_homepage(html: str, base_url: str) -> List[Dict[str, str]]:
    """
    Parse a category homepage HTML, extract article titles + full URLs.
    Looks for <a href="/n1/..."> patterns.
    """
    soup = BeautifulSoup(html, 'html.parser')
    articles = []
    for a in soup.find_all('a', href=True):
        path = a['href']
        if ARTICLE_PATH_RE.match(path):
            title = a.get_text(strip=True)
            # skip empty titles
            if not title:
                continue
            full_url = base_url.rstrip('/') + path
            articles.append({'title': title, 'url': full_url})
    return articles

def extract_top10_ranking(html: str, base_url: str) -> List[Dict[str, str]]:
    """
    Extract the 'Top 10' ranking board from an article page HTML.
    Returns a list of dicts with keys: 'rank', 'title', and 'url'.
    """
    logger = logging.getLogger(__name__)

    soup = BeautifulSoup(html, 'html.parser')
    ranking_div = soup.find('div', class_='rm_ranking')
    if not ranking_div:
        logger.warning("No <div class='rm_ranking'> found on article page.")
        return []

    ul = ranking_div.find('ul', class_='rm_ranking_list')
    if not ul:
        logger.warning("No <ul class='rm_ranking_list'> found inside ranking div.")
        return []

    top10 = []
    for li in ul.find_all('li'):
        rank_tag = li.find('span')
        link_tag = li.find('a', href=True)
        if not rank_tag or not link_tag:
            continue

        rank = rank_tag.get_text(strip=True)
        title = link_tag.get_text(strip=True)
        url = base_url.rstrip('/') + link_tag['href']
        top10.append({
            'rank': rank,
            'title': title,
            'url': url
        })

    return top10

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------

def main():
    results: Dict[str, List[Dict[str, str]]] = {}

    for homepage in HOMEPAGE_URLS:
        html = fetch_page(homepage)
        if not html:
            continue

        # Derive base URL (scheme+host) from homepage
        base = '/'.join(homepage.split('/')[:3])
        articles = parse_homepage(html, base)
        logger.info(f"Found {len(articles)} articles on {homepage}")
        results[homepage] = articles

    # Output results
    for homepage, items in results.items():
        print(f"\nArticles on {homepage}:")
        for it in items:
            print(f" - {it['title']}\n   {it['url']}")
            
    # Extracting Top 10 ranking from last link in last homepage
    if results:
        last_homepage = list(results.keys())[-1]
        last_articles = results[last_homepage]
        if last_articles:
            last_article_url = last_articles[-1]['url']
            html = fetch_page(last_article_url)
            if html:
                top10 = extract_top10_ranking(html, '/'.join(last_article_url.split('/')[:3]))
                if top10:
                    print(f"\nTop 10 Ranking for {last_article_url}:")
                    for item in top10:
                        print(f" - {item['rank']}: {item['title']}\n   {item['url']}")

if __name__ == '__main__':
    main()
