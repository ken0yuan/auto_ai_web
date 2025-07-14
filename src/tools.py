# tools.py
from playwright.sync_api import Page, Locator
from typing import List, Dict

class WebTools:
    def __init__(self, page: Page):
        self.page = page
    
    def click(self, selector: str, timeout: int = 5000) -> None:
        """
        点击页面元素
        :param selector: CSS选择器或XPath
        :param timeout: 超时时间(毫秒)
        """
        element = self.page.locator(selector).first
        element.click(timeout=timeout)
        print(f"Clicked element: {selector}")
    
    def wait(self, condition: str, selector: str = None, timeout: int = 10000) -> None:
        """
        等待页面状态
        :param condition: 等待条件 ('visible', 'hidden', 'attached', 'detached', 'timeout')
        :param selector: 可选，元素选择器
        :param timeout: 超时时间(毫秒)
        """
        if condition == 'timeout':
            self.page.wait_for_timeout(timeout)
            print(f"Waited for {timeout}ms")
        elif selector:
            if condition == 'visible':
                self.page.locator(selector).first.wait_for(state="visible", timeout=timeout)
            elif condition == 'hidden':
                self.page.locator(selector).first.wait_for(state="hidden", timeout=timeout)
            print(f"Waited for element '{selector}' to be {condition}")
        else:
            self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
            print("Waited for DOM content loaded")
    
    def navigate(self, url: str) -> None:
        """
        跳转到指定URL
        :param url: 目标网址
        """
        self.page.goto(url, wait_until="domcontentloaded")
        print(f"Navigated to: {url}")
    
    def get_elements_by_category(self, container: str = "body") -> Dict[str, List[str]]:
        """
        获取页面元素并按类别分类
        :param container: 容器选择器 (默认整个body)
        :return: 按元素类型分类的字典
        """
        container_locator = self.page.locator(container)
        categories = {
            "buttons": [],
            "links": [],
            "inputs": [],
            "images": [],
            "text_elements": []
        }
        
        # 获取按钮
        buttons = container_locator.locator("button, input[type='button'], input[type='submit']")
        for i in range(buttons.count()):
            btn = buttons.nth(i)
            text = btn.text_content().strip() or btn.get_attribute("value") or "Button"
            categories["buttons"].append(text)
        
        # 获取链接
        links = container_locator.locator("a")
        for i in range(links.count()):
            link = links.nth(i)
            text = link.text_content().strip() or link.get_attribute("href") or "Link"
            categories["links"].append(text)
        
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
        return categories

# 使用示例
if __name__ == "__main__":
    from playwright.sync_api import sync_playwright
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        tools = WebTools(page)
        
        # 导航示例
        tools.navigate("https://example.com")
        
        # 等待示例
        tools.wait('visible', 'h1')
        
        # 获取元素分类
        elements = tools.get_elements_by_category()
        print("Page elements:")
        for category, items in elements.items():
            print(f"  {category.capitalize()}: {len(items)} items")
            for item in items[:3]:  # 只显示前3个
                print(f"    - {item}")
            if len(items) > 3:
                print(f"    ... and {len(items)-3} more")
        
        # 点击示例
        tools.click("a[href='/about']")
        
        browser.close()