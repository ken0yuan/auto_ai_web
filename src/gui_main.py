import sys
import asyncio
import base64
import logging
from pathlib import Path

# 在导入其他库之前设置日志级别，避免输出包含长内容的调试信息
logging.basicConfig(level=logging.DEBUG)
# 特别禁用可能输出长内容的库的调试信息
logging.getLogger('qasync').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('playwright').setLevel(logging.WARNING)

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLineEdit, QPushButton, QLabel,
    QScrollArea, QFrame, QTextEdit
)
from PyQt5.QtCore import Qt
from qasync import QEventLoop, asyncSlot
from playwright.async_api import async_playwright

from llm import generate_opera, ui_analyzer
from operate.operate_web import WebController, extract_json_from_response
from dom.dom_elem import get_related_elements
from prompt.prompt_generate import get_updated_state, format_browser_state_prompt
from Prompts import ui_analyzer_expert, task_analyzer, pic_analyzer
from main import extract_operations, parse_agent_output, async_call_with_retry, ENHANCED_PAGE_INIT_SCRIPT 
from playwright.async_api import Browser, BrowserContext, Page

class ChatCard(QFrame):
    """每一轮思考的卡片"""
    def __init__(self, thought_text="", result_text=""):
        super().__init__()
        self.setObjectName("ChatCard")
        layout = QVBoxLayout()
        self.thought_box = QTextEdit()
        self.thought_box.setReadOnly(True)
        self.thought_box.setObjectName("ThoughtBox")
        self.thought_box.setText(thought_text)
        layout.addWidget(QLabel("🤔 思考过程："))
        layout.addWidget(self.thought_box)

        self.result_box = QTextEdit()
        self.result_box.setReadOnly(True)
        self.result_box.setObjectName("ResultBox")
        self.result_box.setText(result_text)
        layout.addWidget(QLabel("✅ 操作结果："))
        layout.addWidget(self.result_box)

        self.setLayout(layout)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Web 自动化 GUI")
        self.resize(1500, 1050)  # ✅ 页面更大

        main_layout = QVBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("请输入要访问的网站网址")
        main_layout.addWidget(QLabel("🌐 网站网址："))
        main_layout.addWidget(self.url_input)

        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("请输入任务描述")
        main_layout.addWidget(QLabel("📝 任务描述："))
        main_layout.addWidget(self.task_input)

        self.start_button = QPushButton("🚀 开始执行任务")
        self.start_button.clicked.connect(self.on_start_clicked)
        main_layout.addWidget(self.start_button)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout()
        self.scroll_content.setLayout(self.scroll_layout)
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area)

        self.setLayout(main_layout)
        self.setStyleSheet(self.load_qss())

    def load_qss(self):
        return """
        QWidget {
            background-color: #1e1e1e;
            color: #e0e0e0;
            font-family: "Segoe UI", "Microsoft YaHei UI", "SF Pro Display", sans-serif;
            font-size: 50px;  /* ✅ 字体更大 */
        }
        QLabel {
            color: #cfcfcf;
            font-weight: bold;
        }
        QLineEdit {
            background-color: #2b2b2b;
            color: #ffffff;
            border: 1px solid #3a3a3a;
            border-radius: 20px;
            padding: 20px;
            font-size: 38px;
        }
        QPushButton {
            background-color: #4a90e2;
            color: white;
            border: none;
            border-radius: 20px;
            padding: 22px;   /* ✅ 按钮更大 */
            font-weight: bold;
            font-size: 38px;
        }
        QPushButton:hover {
            background-color: #5aa0f2;
        }
        #ChatCard {
            background-color: #2b2b2b;
            border-radius: 22px;
            padding: 22px;
            border: 1px solid #3a3a3a;
        }
        QTextEdit {
            background-color: #1e1e1e;
            color: #dcdcdc;
            border: 1px solid #444444;
            border-radius: 18px;
            padding: 18px;
            font-size: 27px;
        }
        """

    def add_chat_card(self, thought, result):
        card = ChatCard(thought, result)
        self.scroll_layout.addWidget(card)
        self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        )

    @asyncSlot()
    async def on_start_clicked(self):
        url = self.url_input.text().strip()
        task = self.task_input.text().strip()
        if not url or not task:
            self.add_chat_card("❌ 请输入网址和任务", "")
            return

        self.start_button.setEnabled(False)
        # self.add_chat_card("🚀 开始执行任务...", "")
        try:
            await self.run_main_logic(url, task)
        except Exception as e:
            self.add_chat_card("💥 出错", str(e))
        finally:
            self.start_button.setEnabled(True)
            self.add_chat_card("✅ 任务结束", "")

    async def run_main_logic(self, input_website, input_task):
        chat_history = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, args=["--start-maximized"])
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1.0,
                color_scheme="dark"
            )
            await context.add_init_script(ENHANCED_PAGE_INIT_SCRIPT)
            # ✅ 直接使用输入的网址
            page = await context.new_page()
            await page.goto(input_website)
            # ✅ 只创建一次 WebController
            controller = WebController()
            controller.set_context(context)
            old_url=input_website
            old_page_count = 1  # 初始页面数量
            num = 0  # 用于标记每次操作的截图文件名
            while True:
                # ✅ 获取当前活跃页面
                switch_page = False
                switch_page, url = await controller._detect_and_switch_page(old_page_count, old_url)
                if switch_page:
                    old_page_count = len(context.pages)
                    old_url = url
                    self.add_chat_card(f"🔄 页面切换到: {url}", "")
                current_page = controller.get_current_page()
                if not current_page:
                    self.add_chat_card("❌ 没有可用页面", "")
                    break
                
                # ✅ 显示当前页面信息
                page_info = f"当前页面: {current_page.url} (页面 {controller.current_page_index + 1}/{len(context.pages)})"
                print(f"📄 {page_info}")
                
                '''try:
                    # ✅ 等待页面完全加载
                    await current_page.wait_for_load_state("domcontentloaded", timeout=5000)
                    await current_page.wait_for_load_state("networkidle", timeout=3000)
                    
                    # ✅ 短暂等待确保页面渲染完成
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    print(f"⚠️ 页面加载等待超时: {e}")
                    # 继续执行，不中断流程'''
                
                # ✅ 基于当前活跃页面截图和获取状态
                JS_PATH = Path(__file__).resolve().parent / "dom/index.js"
                state = await get_updated_state(current_page, JS_PATH)
                screenshot = await current_page.screenshot(path=f"screenshot_{controller.current_page_index}_{num}.png")
                num += 1
                screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')

                #print("1111111\n")

                # ✅ 异步调用大模型
                response = await async_call_with_retry(
                    ui_analyzer, 3, 2,
                    input_task, screenshot_base64, pic_analyzer, chat_history
                )
                #print("2222222\n")
                if response.startswith("函数") or response.startswith("API错误") or response.startswith("调用API失败"):
                    # 截断可能包含图片编码的长响应
                    truncated_response = response[:500] + "...[响应太长已截断]" if len(response) > 500 else response
                    self.add_chat_card("❌ UI 分析器调用失败", truncated_response)
                    break
                print(f"🔍 UI 分析器响应: {response[:500]}...")  # 只打印前500字避免太长
                thought, task, operations = parse_agent_output(response)
                elements = get_related_elements(state.element_tree)
                controller.update_dom_elements(elements)
                #operations += ["[操作：scroll，对象：，内容：200]"]  # 每次结束滚动
                result_logs = []
                done = False  # 用于标记任务是否完成
                if operations:
                    for op in operations:
                        result = await controller.execute_from_string(op)
                        result_logs.append(f"{op}: {result.success} - {result.message}")
                        #chat_history.append({"role": "user", "content": task})
                        chat_history.append({"role": "assistant", "content": f"{op}: {result.success} - {result.message} - {result.error}"})
                        result_logs.append(f"操作的任务: {task}")
                        #result_logs.append(f"历史任务: {chat_history[-1]}")
                        # ✅ 如果是滚动操作，等待更长时间让页面稳定
                        if result.is_done:
                            done = True
                else:
                    result_logs.append("没有提取到有效的操作列表")
                    break

                self.add_chat_card(thought, "\n".join(result_logs))
                if done:
                    break


            await context.close()
            await browser.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()
    with loop:
        loop.run_forever()
