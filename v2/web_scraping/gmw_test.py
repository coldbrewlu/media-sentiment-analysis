import requests
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin

BASE = "https://epaper.gmw.cn/gmrb/html/"

def get_sections_for_date(date_str: str):
    """
    Given a date string 'YYYY-MM-DD', fetch the front page (第01版)
    and extract all section titles and URLs from the version‐directory list.
    Returns a list of (section_title, full_section_url).
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    url = f"{BASE}{dt.year}-{dt.month:02d}/{dt.day:02d}/nbs.D110000gmrb_01.htm"
    r = requests.get(url)
    r.encoding = "utf-8" # Ensure proper encoding
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    sections = []
    # locate the right‐hand list of pages:
    for a in soup.select("div.list_r ul li a#pageLink"):
        title = a.get_text(strip=True)
        href  = a["href"]
        full  = urljoin(url, href)
        sections.append((title, full))
    return sections

def get_articles_in_section(section_url: str):
    """
    Fetches a section page (e.g. 第02版:要闻) and extracts all article titles and URLs.
    Returns a list of (article_title, full_article_url).
    """
    r = requests.get(section_url)
    r.encoding = "utf-8"
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    articles = []
    # locate the left‐hand list of titles:
    for a in soup.select("div.list_l ul li a"):
        title = a.get_text(strip=True)
        href  = a["href"]
        full  = urljoin(section_url, href)
        articles.append((title, full))
    return articles

def get_article_text_and_author(url: str):
    """
    Fetch an article page, extract the author name and
    concatenate all content paragraphs into one passage.
    """
    r = requests.get(url)
    r.encoding = "utf-8"
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # 1) Author
    author_tag = soup.select_one("div.lai span")
    author = None
    if author_tag:
        # e.g. "作者：本报记者 王晓飞"
        author = author_tag.get_text(strip=True).split("：", 1)[-1]

    # 2) Content paragraphs
    content_div = soup.find(id="articleContent")
    paras = content_div.find_all("p") if content_div else []
    # extract text, strip out any empty sections
    texts = [p.get_text(strip=True) for p in paras if p.get_text(strip=True)]
    passage = "\n\n".join(texts)

    return author, passage

if __name__ == "__main__":
    sample_dates = ["2025-07-20", "2025-07-18", "2025-07-19"]
    for date in sample_dates:
        print(f"\n=== {date} ===")
        try:
            secs = get_sections_for_date(date)
            for sec_title, sec_url in secs:
                print(f"\n  [{sec_title}] → {sec_url}")
                # test‐scrape first few articles in that section
                arts = get_articles_in_section(sec_url)[:5]
                for art_title, art_url in arts:
                    print(f"    • {art_title} → {art_url}")
        except Exception as e:
            print(f"  error fetching {date}: {e}")

    sample_articles = [
        "https://epaper.gmw.cn/gmrb/html/2025-07/19/nw.D110000gmrb_20250719_6-01.htm",
        "https://epaper.gmw.cn/gmrb/html/2025-07/19/nw.D110000gmrb_20250719_1-01.htm",
    ]
    for url in sample_articles:
        author, text = get_article_text_and_author(url)
        print(f"URL: {url}\nAuthor: {author}\n\n{text}\n{'='*80}\n")