from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import json
import os
import time

def crawl_gmw_articles():
    keyword = "私营企业"
    url = f"https://zhonghua.gmw.cn/news.htm?q={keyword}"
    driver = webdriver.Chrome()
    wait = WebDriverWait(driver, 15)
    
    results = []
    page = 1
    max_pages = 5  # 可自行调整

    while page <= max_pages:
        print(f"⚙️ 正在抓取第 {page} 页：{url}")
        driver.get(url)

        try:
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'div.searchresult > ul > li')))
            items = driver.find_elements(By.CSS_SELECTOR, 'div.searchresult > ul > li')

            if not items:
                print("❌ 当前页无搜索结果")
                break

            for item in items:
                try:
                    link_element = item.find_element(By.CSS_SELECTOR, 'a')
                    href = link_element.get_attribute('href')
                    title = link_element.text.strip()

                    # 打开详情页
                    driver.execute_script("window.open(arguments[0]);", href)
                    driver.switch_to.window(driver.window_handles[-1])

                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'div.ainr')))
                    content = driver.find_element(By.CSS_SELECTOR, 'div.ainr').text.strip()

                    results.append({
                        "title": title,
                        "url": href,
                        "content": content
                    })

                    driver.close()
                    driver.switch_to.window(driver.window_handles[0])

                except Exception as e:
                    print(f"❌ 抓取失败：{e}")
                    if len(driver.window_handles) > 1:
                        driver.close()
                        driver.switch_to.window(driver.window_handles[0])
                    continue

            # 找“下一页”
            try:
                next_button = driver.find_element(By.LINK_TEXT, '下一页')
                url = next_button.get_attribute('href')
                page += 1
            except:
                print("🔚 没有下一页")
                break

        except Exception as e:
            print(f"❌ 页面加载失败：{e}")
            break

    driver.quit()

    os.makedirs("data", exist_ok=True)
    with open("data/gmw_private_enterprise.jsonl", "w", encoding="utf-8") as f:
        for item in results:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"✅ 共抓取文章 {len(results)} 篇，保存至 data/gmw_private_enterprise.jsonl")

if __name__ == "__main__":
    crawl_gmw_articles()
