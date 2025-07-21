from dom.dom_elem import extract_dom_tree,get_related_elements, DOMElementNode, DOMTextNode
from playwright.async_api import async_playwright
from operate.operate_web import WebController
from pathlib import Path
import asyncio

async def example_usage():
    # 假设你有一个playwright page对象
    elements = []
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )
        context = await browser.new_context(no_viewport=True)  # ✅ 禁用固定 viewport

        page = await context.new_page()
        controller = WebController()
        controller.set_context(context)
        result1 = await controller.operate("navigate", "https://www.wjx.cn/vm/PzznzMy.aspx")
        JS_PATH = Path(__file__).resolve().parent / "dom/index.js"
        root_node, selector_map = await extract_dom_tree(page, JS_PATH)
        
        elements = get_related_elements(root_node)
        print(f"找到 {len(elements)} 个相关元素")
        controller.update_dom_elements(elements)
        operations = [
            "[操作：input，对象：8，内容：张三]",
            "[操作：input，对象：13，内容：1999018391]",
            "[操作：input，对象：18，内容：20]",
            "[操作：scroll，对象：，内容：300]",
            "[操作：wait，对象：，内容：10]"
        ]
        
        for op in operations:
            result = await controller.execute_from_string(op)
            print(f"执行 {op}: {result.success} - {result.message}")
        
    '''
    # 方式1: 直接调用
    result1 = await controller.operate("click", "登录按钮", "")
    print(f"操作结果: {result1.success}, 消息: {result1.message}")
    
    # 方式2: 从字符串解析
    result2 = await controller.execute_from_string("[操作：input，对象：用户名输入框，内容：admin]")
    print(f"操作结果: {result2.success}, 消息: {result2.message}")
    
    # 方式3: 批量操作
'''

if __name__ == "__main__":
    asyncio.run(example_usage())