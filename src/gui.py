import sys
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QSplitter, QStatusBar
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap, QImage

class AutomationGUI(QMainWindow):
    """
    Web自动化助手的主界面类
    
    这个类创建并管理整个GUI界面，包括：
    - 左侧的浏览器截图显示区域
    - 右侧的聊天对话区域
    - 底部的控制按钮区域
    - 状态栏
    """
    def __init__(self):
        """
        初始化GUI界面
        
        设置窗口属性，创建并布局所有UI组件，连接信号槽
        """
        super().__init__()
        # 设置窗口标题和大小
        self.setWindowTitle("Web Automation Assistant")
        self.setGeometry(100, 100, 1200, 800)
        
        # 创建中央部件和主布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局：垂直布局，包含分割器和控制按钮
        main_layout = QVBoxLayout(central_widget)
        
        # 创建水平分割器：左侧浏览器视图，右侧聊天区域
        splitter = QSplitter(Qt.Horizontal)
        
        # =============== 左侧：浏览器截图区域 ===============
        self.browser_widget = QWidget()
        browser_layout = QVBoxLayout(self.browser_widget)
        
        # 截图显示标签，用于显示浏览器截图
        self.screenshot_label = QLabel()
        self.screenshot_label.setAlignment(Qt.AlignCenter)
        self.screenshot_label.setMinimumSize(800, 600)
        self.screenshot_label.setText("Browser view will appear here")
        self.screenshot_label.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        
        browser_layout.addWidget(self.screenshot_label)
        splitter.addWidget(self.browser_widget)
        
        # =============== 右侧：聊天区域 ===============
        self.chat_widget = QWidget()
        chat_layout = QVBoxLayout(self.chat_widget)
        
        # 聊天历史显示区域（只读）
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setMinimumWidth(350)
        chat_layout.addWidget(self.chat_history)
        
        # 输入区域：任务输入框和发送按钮
        input_layout = QHBoxLayout()
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("Enter your task here...")
        self.send_button = QPushButton("Send")
        
        # 输入框占5份，发送按钮占1份
        input_layout.addWidget(self.task_input, 5)
        input_layout.addWidget(self.send_button, 1)
        chat_layout.addLayout(input_layout)
        
        splitter.addWidget(self.chat_widget)
        # 设置分割器比例：左侧800像素，右侧400像素
        splitter.setSizes([800, 400])
        
        main_layout.addWidget(splitter)
        
        # =============== 控制按钮区域 ===============
        control_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Browser")    # 启动浏览器按钮
        self.stop_button = QPushButton("Stop Browser")      # 停止浏览器按钮
        self.reset_button = QPushButton("Reset")             # 重置按钮
        
        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.reset_button)
        
        main_layout.addLayout(control_layout)
        
        # =============== 状态栏 ===============
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        
        # =============== 连接信号槽 ===============
        self.send_button.clicked.connect(self.on_send_task)         # 发送按钮点击事件
        self.start_button.clicked.connect(self.on_start_browser)    # 启动浏览器按钮点击事件
        self.stop_button.clicked.connect(self.on_stop_browser)      # 停止浏览器按钮点击事件
        self.reset_button.clicked.connect(self.on_reset)            # 重置按钮点击事件
        
        # =============== 截图更新定时器 ===============
        self.screenshot_timer = QTimer()
        self.screenshot_timer.timeout.connect(self.update_screenshot)
        self.screenshot_timer.setInterval(1000)  # 每秒更新一次截图
        
        # =============== 控制器引用 ===============
        self.controller = None  # 外部控制器的引用，用于处理业务逻辑

    def set_controller(self, controller):
        """
        设置控制器引用
        
        Args:
            controller: 外部控制器对象，负责处理业务逻辑
        """
        self.controller = controller
        
    def on_start_browser(self):
        """
        启动浏览器按钮的点击事件处理
        
        启动浏览器并开始截图定时器
        """
        if self.controller:
            self.controller.start_browser()
            self.screenshot_timer.start()
            self.status_bar.showMessage("Browser started")
    
    def on_stop_browser(self):
        """
        停止浏览器按钮的点击事件处理
        
        停止浏览器并停止截图定时器
        """
        if self.controller:
            self.controller.stop_browser()
            self.screenshot_timer.stop()
            self.status_bar.showMessage("Browser stopped")
    
    def on_reset(self):
        """
        重置按钮的点击事件处理
        
        重置控制器状态，清空聊天历史
        """
        if self.controller:
            self.controller.reset()
            self.chat_history.clear()
            self.status_bar.showMessage("Session reset")
    
    def on_send_task(self):
        """
        发送任务按钮的点击事件处理
        
        获取用户输入的任务，发送给控制器处理，并在聊天区域显示
        """
        task = self.task_input.text().strip()
        if task and self.controller:
            self.add_message("user", task)          # 在聊天区域显示用户消息
            self.controller.process_task(task)      # 发送任务给控制器处理
            self.task_input.clear()                 # 清空输入框
    
    def add_message(self, sender, message):
        """
        在聊天历史区域添加消息
        
        Args:
            sender (str): 消息发送者，"user"表示用户，其他值表示助手
            message (str): 消息内容
        """
        if sender == "user":
            prefix = "<b>You:</b> "
            color = "#0066cc"  # 蓝色表示用户消息
        else:
            prefix = "<b>Assistant:</b> "
            color = "#009933"  # 绿色表示助手消息
        
        formatted_message = f'<p style="color:{color}; margin:5px 0;">{prefix}{message}</p>'
        self.chat_history.append(formatted_message)
        # 自动滚动到底部，显示最新消息
        self.chat_history.verticalScrollBar().setValue(
            self.chat_history.verticalScrollBar().maximum()
        )
    
    def update_screenshot(self, image_data=None):
        """
        更新浏览器截图显示
        
        Args:
            image_data (bytes, optional): 图像字节数据。如果为None，则不更新图像
        """
        if image_data:
            # 将字节数据转换为QImage，再转换为QPixmap
            image = QImage.fromData(image_data)
            pixmap = QPixmap.fromImage(image)
            # 缩放图像以适应标签大小，保持宽高比
            scaled_pixmap = pixmap.scaled(
                self.screenshot_label.width(), 
                self.screenshot_label.height(),
                Qt.KeepAspectRatio,      # 保持宽高比
                Qt.SmoothTransformation  # 平滑缩放
            )
            self.screenshot_label.setPixmap(scaled_pixmap)
    
    def update_status(self, message):
        """
        更新状态栏消息
        
        Args:
            message (str): 要显示的状态消息
        """
        self.status_bar.showMessage(message)
    
    def closeEvent(self, event):
        """
        窗口关闭事件处理
        
        在窗口关闭前清理资源
        
        Args:
            event: 关闭事件对象
        """
        if self.controller:
            self.controller.cleanup()  # 清理控制器资源
        event.accept()  # 接受关闭事件

if __name__ == "__main__":
    """
    程序入口点
    
    创建QApplication实例，显示主窗口，并启动事件循环
    """
    app = QApplication(sys.argv)
    window = AutomationGUI()
    window.show()
    sys.exit(app.exec_())