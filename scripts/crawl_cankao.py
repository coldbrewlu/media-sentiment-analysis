# 参考消息
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import os
import time

def crawl_articles_scroll(pages=5):
    print("🚀 Scrolling crawler for 参考消息...")

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=options)

    url = "https://m.cankaoxiaoxi.com/statics/h5-news-media/index.html#/?siteId=2b0cbbb1d563414393513f147f7e9799"
    driver.get(url)
    time.sleep(5)  # wait for initial load

    # Scroll loop to trigger lazy loading
    for _ in range(pages):
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)  # wait for articles to load

    anchors = driver.find_elements(By.CLASS_NAME, "uni-news-item")
    links = []

    for a in anchors:
        href = a.get_attribute("href")
        if href:
            if href.startswith("http"):
                links.append(href)
            else:
                links.append("https://m.cankaoxiaoxi.com" + href)

    print(f"✅ Found {len(links)} links.")
    for link in links[:10]:
        print(" -", link)

    os.makedirs("data/raw/cankao", exist_ok=True)
    with open("data/raw/cankao/cankao_links.txt", "w", encoding="utf-8") as f:
        for link in links:
            f.write(link + "\n")

    driver.quit()

if __name__ == "__main__":
    crawl_articles_scroll(pages=10)

