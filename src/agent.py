from llm import call_deepseek_api
import json
from playwright.sync_api import sync_playwright
import re
from playwright.sync_api import TimeoutError

def click_and_maybe_switch_link(context, page, button_name, container=None, timeout_ms=5000):
    exception = False
    try:
        with context.expect_page(timeout=timeout_ms) as new_page_info:
            # 使用更安全的选择器
            button = page.locator(f'a[href*="{button_name}"]')
            if button.count() == 0:
                raise Exception(f"找不到按钮：{button_name}")
            elif button.count() > 1:
                print(f"[!] 有多个匹配项，尝试点击第一个")
                button.n
            else:
                button.click(button="left")
            try:
                new_page = context.wait_for_event("page", timeout=5000)
            except Exception as e:
                print(f"[ℹ] 等待新页面超时，可能是当前页面跳转：{e}")
                all_pages = context.pages
                print(f"[ℹ] 当前打开的页面数量：{len(all_pages)}")
                new_page = all_pages[-1]
            print(f"[✔] 成功点击按钮：{button_name}")
            new_page.wait_for_load_state("domcontentloaded", timeout=15000)
            print("[✔] 切换到新页面")
            page = new_page
    except TimeoutError:
        print("[ℹ] 当前页面跳转，没有新页面打开")
    except Exception as e:
        print(f"[❌] 点击或等待页面过程中出错：{e}")
        exception = True

    if container:
        container_locator = page.locator(container)
        container_locator.wait_for()
        return page, container_locator, exception
    return page, None, exception

def click_and_maybe_switch_button(context, page, button_name, container=None, timeout_ms=5000):
    exception = False
    try:
        with context.expect_page(timeout=timeout_ms) as new_page_info:
            # 使用更安全的选择器
            button = page.get_by_text(button_name, exact=True)
            if button.count() == 0:
                raise Exception(f"找不到按钮：{button_name}")
            elif button.count() > 1:
                print(f"[!] 有多个匹配项，尝试点击第一个")
                button.nth(0).click(button="left")
            else:
                button.click(button="left")
            try:
                new_page = context.wait_for_event("page", timeout=5000)
            except Exception as e:
                print(f"[ℹ] 等待新页面超时，可能是当前页面跳转：{e}")
                all_pages = context.pages
                print(f"[ℹ] 当前打开的页面数量：{len(all_pages)}")
                new_page = all_pages[-1]
            print(f"[✔] 成功点击按钮：{button_name}")
            new_page.wait_for_load_state("domcontentloaded", timeout=15000)
            print("[✔] 切换到新页面")
            page = new_page
    except TimeoutError:
        print("[ℹ] 当前页面跳转，没有新页面打开")
    except Exception as e:
        print(f"[❌] 点击或等待页面过程中出错：{e}")
        exception = True

    if container:
        container_locator = page.locator(container)
        container_locator.wait_for()
        return page, container_locator , exception
    return page, None, exception

def extract_json_from_response(response_text: str):
    # 匹配 {...} 格式的 JSON 子串（非贪婪匹配，支持多行）
    matches = re.findall(r'\{.*?\}', response_text, re.DOTALL)
    for json_str in reversed(matches):
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            continue
    print("未找到 JSON 格式的内容")

input_website = input("请输入要访问的网站网址：")
input_task = input("请输入任务描述：")
chat_history = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()

    page = context.new_page()
    page.goto(input_website)
    print(len(context.pages))
    print(page.title())  # 打印网页标题栏

    container="body"
    # 获取页面元素并按类别分类

    stop_sign = True
    while (stop_sign):
        # 获取按钮
        categories = {
            "buttons": [],
            "links": [],
            "inputs": [],
            "images": [],
            "text_elements": []
        }
        container_locator = page.locator(container)
        buttons = container_locator.locator("button, input[type='button'], input[type='submit']")
        for i in range(buttons.count()):
            btn = buttons.nth(i)
            text = btn.text_content().strip() or btn.get_attribute("value") or "Button"
            categories["buttons"].append(text)
            
            # 获取链接
        links = container_locator.locator("a")
        for i in range(links.count()):
            link = links.nth(i)
            try:
                if link.is_visible():
                    text = link.text_content(timeout=5000).strip() or link.get_attribute("href") or "Link"
                    #print("链接文本：", text)
                    categories["links"].append(text)
            except TimeoutError:
                print(f"第 {i} 个 link 获取文本超时")
            # 获取输入框
        inputs = container_locator.locator("input, textarea, select")
        for i in range(inputs.count()):
            input_elem = inputs.nth(i)
            name = input_elem.get_attribute("name") or input_elem.get_attribute("id") or "Input"
            categories["inputs"].append(name)
            
            # 获取图片
        images = container_locator.locator("img")
        for i in range(images.count()):
            img = images.nth(i)
            alt = img.get_attribute("alt") or "Image"
            categories["images"].append(alt)
            
            # 获取文本元素
        texts = container_locator.locator("p, h1, h2, h3, h4, h5, h6, span, div")
        for i in range(texts.count()):
            text_elem = texts.nth(i)
            if text_elem.count() == 0:  # 确保不是容器元素
                content = text_elem.text_content().strip()
                if content:
                    categories["text_elements"].append(content[:50] + "..." if len(content) > 50 else content)
        
        print(f"Found elements: {sum(len(v) for v in categories.values())} in {container}")
        elements = {
            "buttons": categories["buttons"],
            "links": categories["links"],
            "inputs": categories["inputs"],
            "images": categories["images"],
            "text_elements": categories["text_elements"]
        }
        
        ans = call_deepseek_api(
            input_task, 
            chat_history,
            system_message='你是任务拆分大师，请你根据用户意图，找出完成任务的下一步操作对应的传入页面中最合适的按钮或链接，不能添加任何额外说明或解释，只返回如下格式，如果是按钮，那么是：{"action": "点击", "button": "热点"}，如果是链接，那么是：{"action": "点击", "link": "https//www.bilibili.com/video/BV1ztu3zKEwH"}',
            context=elements
            )
        exception = False
        print("模型返回内容：", ans)
        result=extract_json_from_response(ans)
        if result is None:
            print("模型未返回有效的 JSON 格式")
        else:
            button_name = result.get("button")
            if not button_name:
                button_name = result.get("link")
                print(f"模型返回的链接：{button_name}")
                page,container_locator, exception = click_and_maybe_switch_link(context, page, button_name, container=container)
                if exception:
                    page, container_locator, exception = click_and_maybe_switch_button(context, page, button_name, container=container)
            else:
                if result.get("action") == "完成":
                    print(result.get("message"))
                    stop_sign = False
                elif button_name:
                    print(f"点击按钮: {button_name}")
                    page, container_locator, exception = click_and_maybe_switch_button(context, page, button_name, container=container)
                    if exception:
                        page,container_locator, exception = click_and_maybe_switch_link(context, page, button_name, container=container)   
        if not exception:
            chat_history.append({"role": "user", "content": input_task})
            chat_history.append({"role": "assistant", "content": ans})
            input_task = ("请继续执行任务，直到完成。当前任务描述：" + ans + "\n请继续执行任务，直到完成。")
