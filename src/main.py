from playwright.async_api import async_playwright
from llm import generate_opera, ui_analyzer
from operate.operate_web import WebController, extract_json_from_response
from dom.dom_elem import extract_dom_tree, get_related_elements, DOMElementNode, DOMTextNode
from prompt.prompt_generate import get_updated_state,format_browser_state_prompt
from Prompts import ui_analyzer_expert
import asyncio
import base64
import json
import time
from pathlib import Path

# ---- 示例：你可以把这里换成实际生成的 JSON ----

def extract_operations(response: str):
    """
    从模型返回的字符串中提取任务描述和操作列表
    输入格式：['[任务描述：完成了名字的填写]','[操作：click，对象：登录链接，内容：]', '[操作：input，对象：8，内容：用户名]',...]
    返回：(task_description, operations_list)
    """
    def convert_to_standard_format(operations):
        """将不同格式的操作转换为标准字符串格式"""
        standard_operations = []
        for op in operations:
            if isinstance(op, list) and len(op) >= 3:
                # 格式：["操作：input", "对象：8", "内容：张三"]
                action = op[0].replace("操作：", "").strip()
                target = op[1].replace("对象：", "").strip()
                content = op[2].replace("内容：", "").strip() if len(op) > 2 else ""
                # 转换为标准格式，使用中文逗号
                standard_op = f"[操作：{action}，对象：{target}，内容：{content}]"
                standard_operations.append(standard_op)
            elif isinstance(op, str):
                # 已经是字符串格式，直接使用
                standard_operations.append(op)
        return standard_operations
    
    def parse_operations_array(operations_array):
        """解析操作数组，分离任务描述和操作"""
        task_description = ""
        operations = []
        
        for item in operations_array:
            if isinstance(item, str):
                # 检查是否是任务描述
                if item.startswith('[任务描述：') and item.endswith(']'):
                    task_description = item[5:-1]  # 去掉 '[任务描述：' 和 ']'
                # 检查是否是操作
                elif item.startswith('[操作：') and item.endswith(']'):
                    operations.append(item)
                else:
                    # 其他格式的操作，直接添加
                    operations.append(item)
        
        return task_description, convert_to_standard_format(operations)
    
    try:
        # 首先尝试直接解析整个响应
        operations_array = json.loads(response)
        return parse_operations_array(operations_array)
    except json.JSONDecodeError:
        # 如果失败，尝试从文本中提取JSON数组
        import re
        
        # 查找 ```json 和 ``` 之间的内容
        json_match = re.search(r'```json\s*(\[.*?\])\s*```', response, re.DOTALL)
        if json_match:
            try:
                json_str = json_match.group(1)
                operations_array = json.loads(json_str)
                return parse_operations_array(operations_array)
            except json.JSONDecodeError:
                print(f"无法解析提取的JSON: {json_str}")
        
        # 如果没有找到 ```json``` 格式，尝试查找任何 [ ] 包围的数组
        array_match = re.search(r'\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]', response, re.DOTALL)
        if array_match:
            try:
                array_str = '[' + array_match.group(1) + ']'
                operations_array = json.loads(array_str)
                return parse_operations_array(operations_array)
            except json.JSONDecodeError:
                print(f"无法解析提取的数组: {array_str}")
        
        print("无法从响应中提取操作列表，请检查模型返回格式")
        print(f"原始响应: {response[:200]}...")  # 打印前200字符用于调试
        return "", []

def call_with_retry(func, max_retries=3, delay=2, *args, **kwargs):
    """
    带重试机制的函数调用
    :param func: 要调用的函数
    :param max_retries: 最大重试次数
    :param delay: 重试间隔时间（秒）
    :param args: 函数参数
    :param kwargs: 函数关键字参数
    :return: 函数执行结果
    """
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            print(f"尝试调用 {func.__name__} (第 {attempt + 1} 次)")
            result = func(*args, **kwargs)
            
            # 检查结果是否有效
            if result and not result.startswith("API错误") and not result.startswith("调用API失败"):
                print(f"✅ {func.__name__} 调用成功")
                return result
            else:
                print(f"❌ {func.__name__} 返回错误结果: {result[:100]}...")
                if attempt < max_retries:
                    print(f"⏳ 等待 {delay} 秒后重试...")
                    time.sleep(delay)
                continue
                
        except Exception as e:
            last_error = e
            print(f"❌ {func.__name__} 调用异常: {str(e)}")
            if attempt < max_retries:
                print(f"⏳ 等待 {delay} 秒后重试...")
                time.sleep(delay)
            else:
                print(f"💥 {func.__name__} 重试 {max_retries} 次后仍然失败")
    
    # 所有重试都失败，返回错误信息
    error_msg = f"函数 {func.__name__} 经过 {max_retries + 1} 次尝试后失败"
    if last_error:
        error_msg += f"，最后错误: {str(last_error)}"
    return error_msg

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
            screenshot = await page.screenshot()
            screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')

            JS_PATH = Path(__file__).resolve().parent / "dom/index.js"
            state = await get_updated_state(page, JS_PATH)
            #print(context)
            
            # 第一个大模型调用：UI分析器（带重试）
            print("\n=== 调用 UI 分析器 ===")
            response = call_with_retry(
                ui_analyzer,
                3,  # max_retries
                2,  # delay
                input_task,
                screenshot_base64,
                ui_analyzer_expert,
                chat_history,
            )
            
            # 检查UI分析器调用是否成功
            if response.startswith("函数") or response.startswith("API错误") or response.startswith("调用API失败"):
                #print(f"UI分析器调用失败: {response}")
                print("跳过本次循环...")
                continue
                
            #print(f"\nUI分析器返回：{response}")
            thought, task, place = extract_json_from_response(response)
            elements = get_related_elements(state.element_tree)
            prompt = format_browser_state_prompt(state, place)
            controller.update_dom_elements(elements)
            print(prompt)
            
            # 第二个大模型调用：操作生成器（带重试）
            print("\n=== 调用操作生成器 ===")
            ans = call_with_retry(
                generate_opera,
                3,  # max_retries
                2,  # delay
                task,
                prompt,
                screenshot_base64,
            )
            
            # 检查操作生成器调用是否成功
            if ans.startswith("函数") or ans.startswith("API错误") or ans.startswith("调用API失败"):
                print(f"操作生成器调用失败: {ans}")
                print("跳过本次循环...")
                continue
            print(f"\n操作生成器返回：{ans}")
            task_description, operations = extract_operations(ans)
            
            print(f"任务描述: {task_description}")
            print(f"操作列表: {operations}")
            
            # 执行操作
            if operations:
                for op in operations:
                    result = await controller.execute_from_string(op)
                    print(f"执行 {op}: {result.success} - {result.message}")
            else:
                print("没有提取到有效的操作列表")
                
            chat_history.append({"role": "user", "content": task})
            chat_history.append({"role": "assistant", "content": ans})
            # 使用提取的任务描述来更新input_task
            if task_description:
                input_task = f"请继续执行任务，直到完成。上一步任务：{task_description}\n请继续执行任务，直到完成。"
            else:
                input_task = ("请继续执行任务，直到完成。当前任务描述：" + task + "\n请继续执行任务，直到完成。")

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
