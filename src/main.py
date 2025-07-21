from playwright.async_api import async_playwright
from llm import call_deepseek_api
from operate.operate_web import WebController, extract_json_from_response
from locator.locate_clickable_icon import locate_clickable_icon
from dom.dom_elem import extract_dom_tree, get_related_elements, DOMElementNode, DOMTextNode
import asyncio
from pathlib import Path

# ---- 示例：你可以把这里换成实际生成的 JSON ----

async def main():
    input_website = input("请输入要访问的网站网址：")
    input_task = input("请输入任务描述：")
    chat_history = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )
        context = await browser.new_context(no_viewport=True)  # ✅ 禁用固定 viewport
        page = await context.new_page()
        await page.goto(input_website)
        # 
        # 实例化操作类
        while True:
            controller = WebController()
            controller.set_context(context)
            screen = await page.screenshot()
            JS_PATH = Path(__file__).resolve().parent / "dom/index.js"
            root_node, selector_map = await extract_dom_tree(page, JS_PATH)
            print(context)
            ans = call_deepseek_api(
                input_task, 
                chat_history,
                pic=screen,
            )
            print(f"\n模型返回的操作：{ans}")
            thought,task,place = extract_json_from_response(ans)
            elements = get_related_elements(root_node,place)
            controller.update_dom_elements(elements)
            #input2= task+elements+请根据以上信息和页面执行操作，操作格式是
            ans = call_deepseek_api(
                task, 
                chat_history,
                pic=screen,
            )
            #opearations = ans.
            for op in operations:
                result = await controller.execute_from_string(op)
                print(f"执行 {op}: {result.success} - {result.message}")
            # 依次执行操作
            print("\n开始执行操作：")
            '''if operator.operate(response):
                print("[成功] 执行操作")
                page = operator.page
                chat_history.append({"role": "user", "content": input_task})
                chat_history.append({"role": "assistant", "content": ans})
                input_task = ("请继续执行任务，直到完成。当前任务描述：" + ans + "\n请继续执行任务，直到完成。")
            else:
                print("[跳过] 无法执行操作或操作失败")'''

        context.close()
        browser.close()

if __name__ == "__main__":
    asyncio.run(main())
