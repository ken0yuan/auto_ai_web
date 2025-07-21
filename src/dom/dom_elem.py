import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union

from playwright.async_api import async_playwright

# ========== DOM 节点类 ==========
# ========== 文本节点 ==========
class DOMTextNode:
    def __init__(self, text: str):
        self.text: str = text
        self.parent: Optional["DOMElementNode"] = None

    def __repr__(self):
        return f"<DOMTextNode '{self.text[:15]}...'>"

    def has_parent_with_highlight_index(self):
        p = self.parent
        while p:
            if getattr(p, "highlight_index", None) is not None:
                return True
            p = p.parent
        return False

# ========== 元素节点 ==========
class DOMElementNode:
    def __init__(self, tag_name: str, xpath: str, attributes: Dict[str, str],
                 is_visible: bool = False,
                 bounding_box: Optional[Dict[str, float]] = None):
        self.tag_name = tag_name
        self.xpath = xpath
        self.attributes = attributes
        self.is_visible = is_visible
        self.bounding_box = bounding_box or {}
        self.is_interactive = False
        self.is_top_element = False
        self.highlight_index = None
        self.children: List[Union["DOMElementNode", DOMTextNode]] = []
        self.parent: Optional["DOMElementNode"] = None

    def __repr__(self):
        return f"<DOMNode {self.tag_name} xpath={self.xpath} children={len(self.children)}>"

    # ✅ 完全复刻原始方法
    def get_all_text_till_next_clickable_element(self, max_depth: int = -1) -> str:
        text_parts = []

        def collect_text(node, current_depth):
            if max_depth != -1 and current_depth > max_depth:
                return
            if isinstance(node, DOMElementNode) and node != self and node.highlight_index is not None:
                return
            if isinstance(node, DOMTextNode):
                text_parts.append(node.text.strip())
            elif isinstance(node, DOMElementNode):
                for child in node.children:
                    collect_text(child, current_depth + 1)

        collect_text(self, 0)
        return "\n".join([t for t in text_parts if t]).strip()

# ========== DOM 树构建器 ==========
class DOMTreeBuilder:
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

    async def build_dom_tree(self, eval_page: dict) -> Tuple[DOMElementNode, Dict[int, DOMElementNode]]:
        js_node_map = eval_page["map"]
        js_root_id = eval_page["rootId"]

        selector_map: Dict[int, DOMElementNode] = {}
        node_map: Dict[str, Union[DOMElementNode, DOMTextNode]] = {}

        # 第一步：创建所有节点
        for node_id, node_data in js_node_map.items():
            node, children_ids = self._parse_node(node_data)
            if node is None:
                continue

            node_map[node_id] = node
            if isinstance(node, DOMElementNode) and node.highlight_index is not None:
                selector_map[node.highlight_index] = node

        # 第二步：建立父子关系
        for node_id, node_data in js_node_map.items():
            if node_id not in node_map:
                continue
            
            node = node_map[node_id]
            if not isinstance(node, DOMElementNode):
                continue
                
            children_ids = node_data.get("children", [])
            for child_id in children_ids:
                if child_id in node_map:
                    child_node = node_map[child_id]
                    child_node.parent = node
                    node.children.append(child_node)

        root_node = node_map.get(str(js_root_id))
        if root_node is None or not isinstance(root_node, DOMElementNode):
            raise ValueError("Failed to parse HTML to DOM tree")

        return root_node, selector_map

    def _parse_node(self, node_data: dict) -> Tuple[Optional[Union[DOMElementNode, DOMTextNode]], List[str]]:
        if not isinstance(node_data, dict):
            return None, []
        if node_data.get("type") == "TEXT_NODE":
            return DOMTextNode(node_data.get("text", "")), []

        node = DOMElementNode(
            tag_name=node_data.get("tagName", ""),
            xpath=node_data.get("xpath", ""),
            attributes=node_data.get("attributes", {}),
            is_visible=node_data.get("isVisible", False),
            bounding_box=node_data.get("boundingBox"),
        )
        node.is_top_element = node_data.get("isTopElement", False)
        node.is_interactive = node_data.get("isInteractive", False)
        node.highlight_index = node_data.get("highlightIndex")

        # ✅ 如果 JS 没给 highlightIndex，但该节点是交互节点，则生成一个
        if node.highlight_index is None and node.is_interactive:
            node.highlight_index = hash(node.xpath) % 100000  # 简单生成一个唯一 id

        return node, node_data.get("children", [])

def get_related_elements(node: Union[DOMElementNode, DOMTextNode]) -> List[DOMElementNode]:
    """
    获取与给定节点相关的所有可点击元素
    """
    related_elements = []
    
    if isinstance(node, DOMElementNode) and node.highlight_index is not None:
        # 如果是可点击元素，直接添加
        related_elements.append(node)
    
    # ✅ 递归处理子节点，查找所有可点击元素
    if isinstance(node, DOMElementNode):
        for child in getattr(node, "children", []):
            child_results = get_related_elements(child)
            if child_results:
                related_elements.extend(child_results)
    
    return related_elements

# ========== Playwright 执行 + DOM 树解析 ==========
async def extract_dom_tree(page, js_path: str) -> Tuple[DOMElementNode, dict]:
    """
    基于已经存在的 Playwright Page 对象提取 DOM 树。

    :param page: 已经打开的 playwright.async_api.Page 实例
    :param js_path: index.js 的路径
    :return: (root_node, selector_map)
    """
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger("DOMTree")

    builder = DOMTreeBuilder(logger=logger)

    # 读取 index.js
    js_code = Path(js_path).read_text(encoding="utf-8")

    args = {
        "doHighlightElements": False,
        "focusHighlightIndex": -1,
        "viewportExpansion": 0,
        "debugMode": False
    }

    logger.debug(f"🔧 Running JavaScript DOM analysis for {await page.title()} ({page.url})...")
    eval_page: dict = await page.evaluate(js_code, args)
    logger.debug("✅ JavaScript DOM analysis completed")

    # 构建 DOM 树
    root_node, selector_map = await builder.build_dom_tree(eval_page)
    logger.debug("✅ Python DOM tree construction completed")

    return root_node, selector_map

# ========== 测试入口 ==========
if __name__ == "__main__":
    TEST_URL = "https://www.wjx.cn/vm/PzznzMy.aspx"
    BASE_DIR = Path(__file__).resolve().parent
    JS_PATH = BASE_DIR / "index.js"  # 不再受运行时目录影响

    async def main():
        root, selector_map, browser = await extract_dom_tree(TEST_URL, JS_PATH)
        print("\n=== DOM TREE ROOT ===")
        print(root)
        print("\n=== INTERACTIVE ELEMENTS ===")
        for idx, node in selector_map.items():
            print(f"{node.highlight_index} {node.tag_name} {node.attributes} ")
        await asyncio.sleep(20)  # 等待20秒以查看结果
        
        # 在测试代码结束时关闭浏览器
        await browser.close()

    asyncio.run(main())
