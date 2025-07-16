from playwright.sync_api import Page
import json
import re

def extract_json_from_response(response_text: str):
    # 匹配 {...} 格式的 JSON 子串（非贪婪匹配，支持多行）
    matches = re.findall(r'\{.*?\}', response_text, re.DOTALL)
    for json_str in reversed(matches):
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            continue
    print("未找到 JSON 格式的内容")

class PlaywrightOperator:
    def __init__(self, page: Page):
        self.page = page
        self.context = page.context

    def operate(self, element: dict, auto_switch: bool = True) -> bool:
        """
        执行单个操作
        :param auto_switch: 是否在操作后自动检测并切换页面
        """
        success = self._do_action(element)

        return success

    def _do_action(self, element: dict) -> bool:
        """执行实际的点击或输入逻辑"""
        if not element:
            print("[跳过] 无效的操作元素")
            return False
        tag = element.get("tag")
        type_ = element.get("type")
        text = element.get("text")
        title = element.get("title")
        role = element.get("role")
        class_name = element.get("class")
        content = element.get("ans")

        try:
            if type_ == "checkbox" or role == "checkbox":
                self.page.get_by_role("checkbox", name=text or title or "").check()
                return True

            if tag == "input" and type_ in ["text", "search"]:
                if not content:
                    print(f"[跳过] 输入框需要 content：{element}")
                    return False
                locator = f"input.{class_name.split()[0]}" if class_name else "input"
                self.page.locator(locator).fill(content)
                return True

            if tag == "textarea":
                if not content:
                    print(f"[跳过] textarea 需要 content：{element}")
                    return False
                locator = f"textarea.{class_name.split()[0]}" if class_name else "textarea"
                self.page.locator(locator).fill(content)
                return True

            if text:
                return self.click_and_maybe_switch(f"text={text}")
            if title:
                return self.click_and_maybe_switch(f"[title='{title}']")
            if role:
                return self.click_and_maybe_switch(f"role={role}")
            if class_name:
                first_class = class_name.split(" ")[0]
                return self.click_and_maybe_switch(f".{first_class}")

            print(f"[跳过] 无法定位：{element}")
            return False

        except Exception as e:
            print(f"[错误] 操作失败：{element}，错误信息：{e}")
            return False

    def click_and_maybe_switch(self, locator, timeout_ms=5000) -> bool:
        """
        尝试点击一个元素，并在需要时自动切换到新页面或跳转后的页面
        :param locator: Playwright 的定位器字符串（例如 'text="登录"'、'css=.nav-search-btn'）
        :param timeout_ms: 等待新页面的超时时间
        :return: True 表示成功，False 表示点击失败
        """
        try:
            print(f"[ℹ] 尝试点击元素: {locator}")
            old_pages = len(self.context.pages)

            # 用 expect_page 捕获新页面
            try:
                with self.context.expect_page(timeout=timeout_ms) as new_page_info:
                    self.page.locator(locator).click()
                new_page = new_page_info.value
                new_page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                self.page = new_page
                print("[✔] 新页面已打开并切换成功")
                return True

            except TimeoutError:
                # 没有新页面，可能是当前页面跳转
                print("[ℹ] 没有新页面打开，检测当前页面是否跳转...")
                old_url = self.page.url
                self.page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                if self.page.url != old_url:
                    print(f"[✔] 当前页面跳转成功: {old_url} -> {self.page.url}")
                    return True
                else:
                    print("[ℹ] 页面没有跳转，仍停留在原页面")
                    return True

        except Exception as e:
            print(f"[❌] 点击或等待页面过程中出错：{e}")
            return False