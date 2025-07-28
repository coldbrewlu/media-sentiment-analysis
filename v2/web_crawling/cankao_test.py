from playwright.sync_api import sync_playwright, TimeoutError
from datetime import datetime

def scrape_by_intercept(
    section_slug: str,
    channel_id: str,
    cutoff: str = "2022-01-01",
    page_size: int = 10,
):
    cutoff_date = datetime.strptime(cutoff, "%Y-%m-%d").date()
    start_url = f"https://www.cankaoxiaoxi.com/#/generalColumns/{section_slug}"
    articles = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # mimic real headers
        page.set_extra_http_headers({
            "Referer": "https://www.cankaoxiaoxi.com/",
            "Origin":  "https://www.cankaoxiaoxi.com",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)…"
        })

        #–– DEBUG: log every response URL so we can see what really comes back
        page.on("response", lambda r: print("⮞ RESP", r.url))

        # load the first page (this also fires pageNum=1)
        page.goto(start_url, timeout=20000)
        page.wait_for_selector(".templateModule", timeout=20000)

        page_num = 6
        while True:
            # we expect one XHR per click that contains both our channelId & pageNum
            def is_my_api(r):
                return (
                    "contentapi/api/content/getContentList" in r.url
                    and f"channelId={channel_id}" in r.url
                    and f"pageNum={page_num}" in r.url
                )

            try:
                # wrap the click in expect_response so we get that JSON
                with page.expect_response(is_my_api, timeout=60000) as ev:
                    # on first iteration we already loaded page 1 by goto,
                    # so only after that do we click “加载更多”
                    if page_num > 1:
                        page.click(".generalColumns-loadMore")
                    # give the JS a moment
                    page.wait_for_timeout(20000)
                resp = ev.value
            except TimeoutError:
                print(f"⚠️ timed out waiting for pageNum={page_num}")
                break

            data = resp.json()
            items = data.get("list", [])
            if not items:
                print(f"⚠️ API returned no items on page {page_num}")
                break

            # pull out each article
            for itm in items:
                dts = itm["data"]["publishTime"].split()[0]
                dt  = datetime.strptime(dts, "%Y-%m-%d").date()
                articles.append((dt, itm["data"]["title"], itm["data"]["url"]))

            earliest = min(a[0] for a in articles)
            print(f"[Page {page_num}] got {len(items)} items, earliest so far = {earliest}")

            if earliest < cutoff_date:
                print(f"✅ reached cutoff {cutoff_date}, stopping")
                break

            page_num += 1

        browser.close()

    # sort newest→oldest
    articles.sort(key=lambda x: x[0], reverse=True)

    print("\n--- FIRST 20 ARTICLES ---")
    for dt, t, u in articles[:20]:
        print(dt, t, "→", u)

    print("\n--- LAST 20 ARTICLES ---")
    for dt, t, u in articles[-20:]:
        print(dt, t, "→", u)


if __name__ == "__main__":
    scrape_by_intercept(
        section_slug="zhongguo",
        channel_id="4946bc18c5c94ad6bca5efc0aca2146a",
        cutoff="2022-01-01",
    )
