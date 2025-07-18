from playwright.sync_api import sync_playwright
from llm import call_deepseek_api
from operate.operate_web import PlaywrightOperator, extract_json_from_response
from locator.locate_clickable_icon import locate_clickable_icon

# ---- 示例：你可以把这里换成实际生成的 JSON ----

def main():
    input_website = input("请输入要访问的网站网址：")
    input_task = input("请输入任务描述：")
    chat_history = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        page.goto(input_website)
        # 
        # 实例化操作类
        while True:
            operator = PlaywrightOperator(page)
            context = locate_clickable_icon(page)
            print(context)
            ans = call_deepseek_api(
                input_task, 
                chat_history,
                context=context
            )
            print(f"\n模型返回的操作：{ans}")
            response = extract_json_from_response(ans)
            # 依次执行操作
            print("\n开始执行操作：")
            if operator.operate(response):
                print("[成功] 执行操作")
                page = operator.page
                chat_history.append({"role": "user", "content": input_task})
                chat_history.append({"role": "assistant", "content": ans})
                input_task = ("请继续执行任务，直到完成。当前任务描述：" + ans + "\n请继续执行任务，直到完成。")
            else:
                print("[跳过] 无法执行操作或操作失败")

        context.close()
        browser.close()

if __name__ == "__main__":
    main()
