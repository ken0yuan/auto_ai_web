import asyncio
from pathlib import Path
import sys
import os
import json
sys.path.append(str(Path(__file__).resolve().parent.parent))  # 添加上级目录到 sys.path
#print("Current sys.path:", sys.path)
from dom.dom_elem import extract_dom_tree, DOMElementNode, DOMTextNode

from playwright.async_api import async_playwright

# ========== 数据结构模拟 ==========
class TabInfo:
    def __init__(self, page_id: int, url: str, title: str):
        self.page_id = page_id
        self.url = url
        self.title = title

class PageInfo:
    def __init__(self, viewport_width, viewport_height, page_width, page_height, scroll_y):
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.page_width = page_width
        self.page_height = page_height
        self.scroll_y = scroll_y

class BrowserStateSummary:
    def __init__(self, element_tree, url, title, tabs, page_info, pixels_above, pixels_below):
        self.element_tree = element_tree
        self.url = url
        self.title = title
        self.tabs = tabs
        self.page_info = page_info
        self.pixels_above = pixels_above
        self.pixels_below = pixels_below

# ========== clickable_elements_to_string ==========

def clickable_elements_to_string(node, include_attributes=None, depth=0):
    formatted_text = []
    if include_attributes is None:
        include_attributes = ["id", "name", "aria-label", "placeholder", "title", "role"]

    # ✅ 处理文本节点 - 显示所有可见文本
    '''if isinstance(node, DOMTextNode):
        if node.parent and node.parent.is_visible and node.parent.is_top_element:
            text = node.text.strip()
            if text:
                formatted_text.append(text)'''

    # ✅ 处理可点击的元素节点
    if isinstance(node, DOMElementNode) and node.highlight_index is not None:
        # 获取该元素的文本内容
        text = node.get_all_text_till_next_clickable_element()
        attr_str = " ".join(
            f"{k}='{v}'" for k, v in node.attributes.items()
            if k in include_attributes and v
        )
        if attr_str or text:
            line = f"[{node.highlight_index}]<{node.tag_name}"
            if attr_str:
                line += f" {attr_str}"
            if text:
                line += f" >{text}"
            if node.bounding_box:
                line += f" [box:{json.dumps(node.bounding_box)}]"
            line += " />"
            formatted_text.append(line)

    # ✅ 递归处理子节点
    if isinstance(node, DOMElementNode):
        for child in getattr(node, "children", []):
            child_result = clickable_elements_to_string(child, include_attributes, depth + 1)
            if child_result.strip():
                formatted_text.append(child_result)

    return " ".join([t for t in formatted_text if t.strip()])

# ========== 格式化为 LLM Prompt ==========
def format_browser_state_prompt(state: BrowserStateSummary) -> str:
    tabs_text = "\n".join([f"Tab {t.page_id}: {t.url} - {t.title[:30]}" for t in state.tabs])
    current_tab = next((t.page_id for t in state.tabs if t.url == state.url and t.title == state.title), None)
    current_tab_text = f"Current tab: {current_tab}" if current_tab else ""

    pi = state.page_info
    pages_above = state.pixels_above / pi.viewport_height if pi.viewport_height else 0
    pages_below = state.pixels_below / pi.viewport_height if pi.viewport_height else 0
    total_pages = pi.page_height / pi.viewport_height if pi.viewport_height else 0
    position = pi.scroll_y / max(pi.page_height - pi.viewport_height, 1)
    page_info_text = (
        f"Page info: {pi.viewport_width}x{pi.viewport_height}px viewport, "
        f"{pi.page_width}x{pi.page_height}px total page size, "
        f"{pages_above:.1f} pages above, {pages_below:.1f} pages below, "
        f"{total_pages:.1f} total pages, at {position:.0%} of page"
    )

    elements_text = clickable_elements_to_string(state.element_tree)
    if not elements_text:
        elements_text = "empty page"
    else:
        elements_text = f"[Start of page]\n{elements_text}"

    if state.pixels_above > 0:
        elements_text = f"... {state.pixels_above} pixels above ({pages_above:.1f} pages) ...\n" + elements_text
    if state.pixels_below > 0:
        elements_text += f"\n... {state.pixels_below} pixels below ({pages_below:.1f} pages) - scroll to see more or extract structured data if you are looking for specific information ..."

    return f"""{current_tab_text}
Available tabs:
{tabs_text}
{page_info_text}
Interactive elements from top layer of the current page inside the viewport:
{elements_text}"""

# ========== 完整状态更新（模拟 _get_updated_state）==========
async def get_updated_state(url: str, js_path: str) -> BrowserStateSummary:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )
        context = await browser.new_context(no_viewport=True)  # ✅ 禁用固定 viewport
        page = await context.new_page()
        await page.goto(url)

        # DOM 树
        root_node, selector_map = await extract_dom_tree(page, js_path)

        # Tabs
        pages = browser.contexts[0].pages  # ✅ 修复：不用 await
        tabs = []
        for i, pg in enumerate(pages, start=1):
            tabs.append(TabInfo(i, pg.url, await pg.title()))

        # Page Info
        viewport = page.viewport_size or {"width": 1920, "height": 1080}
        page_width = await page.evaluate("document.documentElement.scrollWidth")
        page_height = await page.evaluate("document.documentElement.scrollHeight")
        scroll_y = await page.evaluate("window.scrollY")
        page_info = PageInfo(viewport["width"], viewport["height"], page_width, page_height, scroll_y)

        pixels_above = scroll_y
        pixels_below = max(page_height - (scroll_y + viewport["height"]), 0)
        title = await page.title()

        await browser.close()
        return BrowserStateSummary(root_node, url, title, tabs, page_info, pixels_above, pixels_below)

# ========== 主程序 ==========
async def main():
    TEST_URL = "https://www.wjx.cn/vm/PzznzMy.aspx"  # 你也可以替换为任意网址
    JS_PATH = Path(__file__).resolve().parent.parent / "dom/index.js"

    state = await get_updated_state(TEST_URL, JS_PATH)
    prompt = format_browser_state_prompt(state)
    print("\n=== ✅ LLM Prompt ===")
    print(prompt)

if __name__ == "__main__":
    asyncio.run(main())
