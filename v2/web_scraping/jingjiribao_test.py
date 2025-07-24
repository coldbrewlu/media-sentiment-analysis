import requests
from bs4 import BeautifulSoup
import time
import re

BASE_URL = "https://www.jingjiribao.cn/"
PAGE_PARAM = "?pageNumber="

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def extract_articles(html):
    soup = BeautifulSoup(html, "html.parser")
    articles = []

    # The list of article titles lives under a ul with class "data-list"
    # Each article is in a li element under a h3
    for li in soup.select("ul.data-list > li"):
        # Extract title and link
        h3 = li.find("h3")
        if not h3:
            continue
        a_tag = h3.find("a")
        if not a_tag:
            continue
        title = a_tag.get_text(strip=True)
        link = a_tag["href"]

        # Extract datetime
        subinfo = li.find("p", class_="subinfo")
        date = None
        if subinfo:
            match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", subinfo.get_text())
            if match:
                date = match.group(1)

        articles.append({"title": title, "link": link, "date": date})

    return articles

def fetch_article(url):
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # 1) author
    author_tag = soup.select_one("span.authors")
    author = author_tag.get_text(strip=True) if author_tag else "Unknown"

    # 2) combine all <p> under .news-content
    paras = []
    for p in soup.select("div.news-content p"):
        text = p.get_text(strip=True)
        if text:
            paras.append(text)

    content = "\n\n".join(paras) 
    return author, content

def scrape_pages(start_page=1, end_page=3, delay=1.5):
    all_articles = []
    for page in range(start_page, end_page + 1):
        url = BASE_URL + PAGE_PARAM + str(page)
        print(f"Scraping {url}")
        try:
            response = requests.get(url, headers=HEADERS)
            response.raise_for_status()
            page_articles = extract_articles(response.text)
            all_articles.extend(page_articles)
        except Exception as e:
            print(f"Error scraping page {page}: {e}")
        time.sleep(delay)  # Be polite

    return all_articles


if __name__ == "__main__":
    results = scrape_pages(start_page=1, end_page=3)
    for article in results:
        print(article)
    for article in results[-2:]:
        author, content = fetch_article(article["link"])
        print(f"Title: {article['title']}")
        print(f"Author: {author}")
        print(f"Content: {content[:100]}...")
