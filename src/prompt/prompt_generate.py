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

def include_node(bounding_box, place):
    """
    检查元素的 bounding_box 是否在指定的 place 范围内
    """
    if not bounding_box:
        return False
    #print(f"Bounding box: {bounding_box}, Place: {place}")
    x1, y1, x2, y2 = bounding_box['x'], bounding_box['y'], bounding_box['width'], bounding_box['height']
    return (place[0] <= x1 <= place[2] or place[0] <= x1+x2 <= place[2]) and\
           (place[1] <= y1 <= place[3] or place[1] <= y1+y2 <= place[3]) and\
           (place[0] <= x1+x2/2 <= place[2] and place[1] <= y1+y2/2 <= place[3]) 

def clickable_elements_to_string(node, place, include_attributes=None, depth=0):
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
        if (attr_str or text) and include_node(node.bounding_box, place):
            line = f"[{node.highlight_index}]<{node.tag_name}"
            if attr_str:
                line += f" {attr_str}"
            if text:
                line += f" >{text}"
            line += " />"
            formatted_text.append(line)

    # ✅ 递归处理子节点
    if isinstance(node, DOMElementNode):
        for child in getattr(node, "children", []):
            child_result = clickable_elements_to_string(child, place, include_attributes, depth + 1)
            if child_result.strip():
                formatted_text.append(child_result)

    return " ".join([t for t in formatted_text if t.strip()])

# ========== 格式化为 LLM Prompt ==========
def format_browser_state_prompt(state: BrowserStateSummary, place) -> str:
    """
    将浏览器状态格式化为LLM可理解的prompt
    """
    # 标签页信息
    tabs_text = "\n".join([f"标签页 {t.page_id}: {t.title[:50]} ({t.url})" for t in state.tabs])
    current_tab = next((t.page_id for t in state.tabs if t.url == state.url and t.title == state.title), None)
    current_tab_text = f"当前标签页: {current_tab}" if current_tab else "当前标签页: 主页面"

    # 页面信息
    pi = state.page_info
    pages_above = state.pixels_above / pi.viewport_height if pi.viewport_height else 0
    pages_below = state.pixels_below / pi.viewport_height if pi.viewport_height else 0
    scroll_position = f"滚动位置: {int(pi.scroll_y)}px"
    if pages_above > 0:
        scroll_position += f" (上方还有 {pages_above:.1f} 屏内容)"
    if pages_below > 0:
        scroll_position += f" (下方还有 {pages_below:.1f} 屏内容)"
    
    page_info_text = (
        f"页面尺寸: 视口 {pi.viewport_width}x{pi.viewport_height}px, "
        f"总页面 {pi.page_width}x{pi.page_height}px\n"
        f"{scroll_position}"
    )

    # 转换place坐标为像素坐标用于计算
    place_pixels = [place[0]*pi.viewport_width, place[1]*pi.viewport_height, place[2]*pi.viewport_width, place[3]*pi.viewport_height]
    place_text = f"[{place_pixels[0]}, {place_pixels[1]}, {place_pixels[2]}, {place_pixels[3]}]"
    #print(place_text)
    # 可交互元素
    elements_text = clickable_elements_to_string(state.element_tree, place=place_pixels)
    if not elements_text:
        elements_text = "当前视口内没有可交互的元素"
    else:
        elements_text = f"当前视口内的可交互元素:\n{elements_text}"

    # 滚动提示
    scroll_hints = []
    if state.pixels_above > 0:
        scroll_hints.append(f"页面上方还有 {pages_above:.1f} 屏内容，可以向上滚动查看")
    if state.pixels_below > 0:
        scroll_hints.append(f"页面下方还有 {pages_below:.1f} 屏内容，可以向下滚动查看")
    
    scroll_hint_text = "\n".join(scroll_hints) if scroll_hints else ""

    # 组装最终prompt
    prompt_parts = [
        f"网页标题: {state.title}",
        f"网页地址: {state.url}",
        "",
        current_tab_text,
        f"可用标签页:\n{tabs_text}",
        "",
        page_info_text,
        "",
        f"当前视口可交互元素所处矩形框的左上角和右下角坐标:{place_text}",
        elements_text
    ]
    
    if scroll_hint_text:
        prompt_parts.extend(["", "导航提示:", scroll_hint_text])

    return "\n".join(prompt_parts)

# ========== 完整状态更新（模拟 _get_updated_state）==========
async def get_updated_state(page, js_path: str) -> BrowserStateSummary:
    """
    从已有的page对象获取浏览器状态
    """
    # DOM 树
    root_node, selector_map = await extract_dom_tree(page, js_path)

    # 获取浏览器上下文中的所有页面
    context = page.context
    pages = context.pages
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
    url = page.url

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
