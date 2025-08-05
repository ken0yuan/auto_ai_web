from playwright.async_api import async_playwright
from llm import generate_opera, ui_analyzer
from operate.operate_web import WebController, extract_json_from_response
from dom.dom_elem import extract_dom_tree, get_related_elements, DOMElementNode, DOMTextNode
from prompt.prompt_generate import get_updated_state,format_browser_state_prompt
from Prompts import pic_analyzer
import asyncio
import base64
import json
import time
from pathlib import Path
import re
from typing import Dict, Any, List, Tuple
# ---- 示例：你可以把这里换成实际生成的 JSON ----

ENHANCED_PAGE_INIT_SCRIPT = """
(() => {
    // 确保脚本只被初始化一次
    if (window._eventListenerTrackerInitialized) return;
    window._eventListenerTrackerInitialized = true;

    // 原始的 addEventListener 函数
    const originalAddEventListener = EventTarget.prototype.addEventListener;
    // 使用 WeakMap 来存储每个元素的事件监听器，避免内存泄漏
    const eventListenersMap = new WeakMap();

    // 重写 addEventListener
    EventTarget.prototype.addEventListener = function(type, listener, options) {
        if (typeof listener === "function") {
            let listeners = eventListenersMap.get(this);
            if (!listeners) {
                listeners = [];
                eventListenersMap.set(this, listeners);
            }
            listeners.push({
                type,
                listener,
                // 只记录函数的前100个字符作为预览，避免存储过多信息
                listenerPreview: listener.toString().slice(0, 100),
                options
            });
        }
        // 调用原始的 addEventListener，保持原有功能
        return originalAddEventListener.call(this, type, listener, options);
    };

    // 定义一个新的全局函数，用于获取元素的监听器
    window.getEventListenersForNode = (node) => {
        const listeners = eventListenersMap.get(node) || [];
        // 返回一个简化的监听器信息列表，对外部调用者友好
        return listeners.map(({ type, listenerPreview, options }) => ({
            type,
            listenerPreview,
            options
        }));
    };
})();
"""

def parse_agent_output(response: str) -> Tuple[str, str, List[str]]:
    """
    从模型返回中解析出 thinking、task 和 operations 字符串格式
    支持 response 为带 markdown ```json 的字符串
    返回: (thinking, task, operations_list)
    """
    # 1. 去除 markdown 的 ```json 包裹
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', response, re.DOTALL)
    if json_match:
        response = json_match.group(1).strip()
    else:
        # 如果不是 markdown 格式，也允许直接是 JSON 字符串
        response = response.strip()

    # 2. 尝试解析 JSON
    try:
        data = json.loads(response)
    except json.JSONDecodeError as e:
        print("❌ JSON 解析失败:", e)
        print("原始 response:", response[:300])
        return "", "", []

    # 3. 提取字段
    thinking = data.get("thinking", "")
    task = data.get("task", "")
    
    operations = []
    for op in data.get("operations", []):
        operations.append(
            f"[操作：{op.get('action', '')}，对象：{op.get('target', '')}，内容：{op.get('content', '')}]"
        )

    return thinking, task, operations

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



# ✅ 改造：异步的 call_with_retry（避免阻塞）
async def async_call_with_retry(func, max_retries=3, delay=2, *args, **kwargs):
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            print(f"尝试调用 {func.__name__} (第 {attempt + 1} 次)")
            # ✅ 在线程池里运行阻塞型函数
            result = await asyncio.to_thread(func, *args, **kwargs)

            if result and not result.startswith("API错误") and not result.startswith("调用API失败"):
                print(f"✅ {func.__name__} 调用成功")
                return result
            else:
                print(f"❌ {func.__name__} 返回错误结果: {result[:100]}...")
                if attempt < max_retries:
                    await asyncio.sleep(delay)
                continue
        except Exception as e:
            last_error = e
            print(f"❌ {func.__name__} 调用异常: {str(e)}")
            if attempt < max_retries:
                await asyncio.sleep(delay)
            else:
                print(f"💥 {func.__name__} 重试 {max_retries} 次后仍然失败")

    return f"函数 {func.__name__} 经过 {max_retries + 1} 次尝试后失败，最后错误: {str(last_error)}" if last_error else "调用失败"

# 参考 gui_main.py 的 run_main_logic 进行异步多轮任务处理，支持多页面、截图、UI分析、操作执行、历史追踪
async def process_task(url: str, task: str):
    input_website = url
    input_task = task
    chat_history = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1.0,
            color_scheme="dark"
        )
        await context.add_init_script(ENHANCED_PAGE_INIT_SCRIPT)
        # 可选：注入 ENHANCED_PAGE_INIT_SCRIPT（如需事件监听器追踪，可参考 gui_main.py）
        # await context.add_init_script(ENHANCED_PAGE_INIT_SCRIPT)
        page = await context.new_page()
        await page.goto(input_website)
        controller = WebController()
        controller.set_context(context)
        old_url = input_website
        old_page_count = 1
        num = 0  # 截图编号
        while True:
            # 检查是否有新页面切换
            switch_page = False
            if hasattr(controller, '_detect_and_switch_page'):
                switch_page, url = await controller._detect_and_switch_page(old_page_count, old_url)
                if switch_page:
                    old_page_count = len(context.pages)
                    old_url = url
                    print(f"🔄 页面切换到: {url}")
            current_page = controller.get_current_page() if hasattr(controller, 'get_current_page') else page
            if not current_page:
                print("❌ 没有可用页面")
                break
            page_info = f"当前页面: {current_page.url} (页面 {getattr(controller, 'current_page_index', 0) + 1}/{len(context.pages)})"
            print(f"📄 {page_info}")

            # 页面状态与截图
            JS_PATH = Path(__file__).resolve().parent / "dom/index.js"
            state = await get_updated_state(current_page, JS_PATH)
            screenshot = await current_page.screenshot(path=f"screenshot_{getattr(controller, 'current_page_index', 0)}_{num}.png")
            num += 1
            screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')

            # 异步调用大模型（UI分析器）
            # 这里直接用 call_with_retry，若需完全异步可仿照 gui_main.py 的 async_call_with_retry
            response = await async_call_with_retry(
                ui_analyzer, 3, 2,
                input_task, screenshot_base64, pic_analyzer, chat_history
            )
            if response.startswith("函数") or response.startswith("API错误") or response.startswith("调用API失败"):
                truncated_response = response[:500] + "...[响应太长已截断]" if len(response) > 500 else response
                print("❌ UI 分析器调用失败", truncated_response)
                break
            print(f"🔍 UI 分析器响应: {response[:500]}...")
            thought, task, operations = parse_agent_output(response)
            elements = get_related_elements(state.element_tree)
            controller.update_dom_elements(elements)
            result_logs = []
            done = False
            if operations:
                for op in operations:
                    result = await controller.execute_from_string(op)
                    result_logs.append(f"{op}: {result.success} - {result.message}")
                    chat_history.append({"role": "assistant", "content": f"{op}: {result.success} - {result.message} - {result.error}"})
                    result_logs.append(f"操作的任务: {task}")
                    if result.is_done:
                        done = True
            else:
                result_logs.append("没有提取到有效的操作列表")
                break
            print("\n".join(result_logs))
            if done:
                break

        await context.close()
        await browser.close()

if __name__ == "__main__":
    url=input("请输入要访问的网站网址：")
    task=input("请输入任务描述：")
    asyncio.run(process_task(url, task))
