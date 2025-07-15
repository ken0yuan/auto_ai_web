def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.bilibili.com/")
    with page.expect_popup() as page1_info:
        page.locator("#nav-searchform div").nth(2).click()
    page1 = page1_info.value
    page.get_by_text("剁手指、关铁笼、强迫卖淫……电诈回流人员讲述缅北噩梦").click()
    with page1.expect_popup() as page2_info:
        page1.goto("https://search.bilibili.com/all?keyword=%E7%8C%AB%E5%A6%96%E7%9A%84%E8%AF%B1%E6%83%91&search_source=1")
    page2 = page2_info.value
    page2.get_by_title("点赞（Q）").click()
    page2.locator(".bili-mini-close-icon").click()
    page2.get_by_role("button", name="最新").click()
    page2.locator(".bili-mini-close-icon").click()
    page2.locator("#mirror-vdcon div").filter(has_text="央视新闻 发消息 中央广播电视总台央视新闻官方账号 充电 关注 2168.1万").nth(3).click()
    page2.locator("div").filter(has_text=re.compile(r"^充电$")).click()
    with page2.expect_popup() as page3_info:
        page2.locator("#nav-searchform div").nth(2).click()
    page3 = page3_info.value
    with page3.expect_popup() as page4_info:
        page3.get_by_role("link", name="【吐槽】《永夜星河》你真的让我恨铁不成钢啊！", exact=True).click()
    page4 = page4_info.value

    # ---------------------
    context.close()
    browser.close()