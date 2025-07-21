import asyncio
import json
import logging
import re
from typing import Generic, TypeVar, Any, Dict, List, Optional, Union
from playwright.sync_api import Page, BrowserContext
from pydantic import BaseModel
from dataclasses import dataclass

logger = logging.getLogger(__name__)

Context = TypeVar('Context')

# 假设你的DOMElementNode和DOMTextNode类已经定义
class DOMTextNode:
    def __init__(self, text: str):
        self.text = text

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

# 参数模型定义
class BaseAction(BaseModel):
    pass

class ClickAction(BaseAction):
    target: str  # 对象：要点击的目标 (编号、xpath、或文本)
    description: str = ""

class InputAction(BaseAction):
    target: str  # 对象：要输入的目标
    content: str  # 内容：要输入的内容

class SearchAction(BaseAction):
    query: str  # 内容：搜索关键词

class NavigateAction(BaseAction):
    url: str  # 对象：要访问的URL

class WaitAction(BaseAction):
    seconds: float = 3.0  # 内容：等待时间

class ScrollAction(BaseAction):
    direction: str = "down"  # 对象：滚动方向 up/down
    distance: int = 500  # 内容：滚动距离

class SelectAction(BaseAction):
    target: str  # 对象：下拉框的编号或选择器
    option: str  # 内容：要选择的选项文本

# 操作结果
@dataclass
class ActionResult:
    success: bool = True
    message: str = ""
    extracted_content: str = ""
    error: str = ""
    is_done: bool = False
    page_changed: bool = False  # 标记是否发生了页面变化
    new_page_url: str = ""  # 新页面的URL

# Registry类
class WebRegistry(Generic[Context]):
    def __init__(self):
        self.actions: Dict[str, Any] = {}
        
    def action(self, description: str, param_model: type = None):
        """装饰器，用于注册动作"""
        def decorator(func):
            action_name = func.__name__
            self.actions[action_name] = {
                'func': func,
                'description': description,
                'param_model': param_model
            }
            return func
        return decorator
    
    async def execute_action(self, action_name: str, params: Any, **kwargs) -> ActionResult:
        """执行指定的动作"""
        if action_name not in self.actions:
            return ActionResult(success=False, error=f"未知操作: {action_name}")
        
        action_info = self.actions[action_name]
        func = action_info['func']
        
        try:
            result = await func(params, **kwargs)
            return result if isinstance(result, ActionResult) else ActionResult(message=str(result))
        except Exception as e:
            logger.error(f"执行操作 {action_name} 时出错: {e}")
            return ActionResult(success=False, error=str(e))

# 主控制器类
class WebController(Generic[Context]):
    def __init__(self):
        self.registry = WebRegistry[Context]()
        self.context: Optional[BrowserContext] = None
        self.current_page_index = 0  # 跟踪当前活跃页面的索引
        self.dom_elements: Dict[int, DOMElementNode] = {}  # 存储编号到DOM元素的映射
        self.xpath_to_element: Dict[str, DOMElementNode] = {}  # xpath到元素的映射
        
        # 注册所有默认操作
        self._register_default_actions()
    
    def set_context(self, context: BrowserContext):
        """设置浏览器上下文"""
        self.context = context
        if context.pages:
            self.current_page_index = len(context.pages) - 1  # 默认使用最新页面
    
    def get_current_page(self) -> Optional[Page]:
        """获取当前活跃的页面"""
        if not self.context or not self.context.pages:
            return None
        
        # 确保索引有效
        if self.current_page_index >= len(self.context.pages):
            self.current_page_index = len(self.context.pages) - 1
        
        return self.context.pages[self.current_page_index]
    
    async def _detect_and_switch_page(self, old_page_count: int, old_url: str) -> tuple[bool, str]:
        """
        检测页面变化并自动切换
        返回: (是否发生变化, 新页面URL)
        """
        if not self.context:
            return False, ""
        
        new_page_count = len(self.context.pages)
        
        # 情况1: 有新页面打开
        if new_page_count > old_page_count:
            # 切换到最新页面
            self.current_page_index = new_page_count - 1
            new_page = self.get_current_page()
            if new_page:
                try:
                    await new_page.wait_for_load_state("domcontentloaded", timeout=5000)
                    logger.info(f"🔗 检测到新页面，自动切换到页面 {self.current_page_index}: {new_page.url}")
                    return True, new_page.url
                except:
                    logger.warning("新页面加载超时")
                    return True, new_page.url
        
        # 情况2: 当前页面发生导航
        current_page = self.get_current_page()
        if current_page:
            try:
                # 等待页面加载完成
                await current_page.wait_for_load_state("domcontentloaded", timeout=3000)
                current_url = current_page.url
                
                if current_url != old_url:
                    logger.info(f"🔗 页面导航: {old_url} -> {current_url}")
                    return True, current_url
            except:
                # 超时或其他错误，可能页面没有导航
                pass
        
        return False, old_url
    
    def update_dom_elements(self, elements: List[DOMElementNode]):
        """
        更新DOM元素映射
        :param elements: DOMElementNode对象列表
        """
        self.dom_elements.clear()
        self.xpath_to_element.clear()
        
        for element in elements:
            # 按highlight_index索引
            if element.highlight_index is not None:
                self.dom_elements[element.highlight_index] = element
                logger.debug(f"映射元素 [{element.highlight_index}] {element.tag_name} -> {element.xpath}")
            
            # 按xpath索引
            if element.xpath:
                self.xpath_to_element[element.xpath] = element
    
    def get_element_by_index(self, index: int) -> Optional[DOMElementNode]:
        """根据编号获取DOM元素"""
        return self.dom_elements.get(index)
    
    def get_element_by_xpath(self, xpath: str) -> Optional[DOMElementNode]:
        """根据xpath获取DOM元素"""
        return self.xpath_to_element.get(xpath)
    
    def _is_element_index(self, target: str) -> bool:
        """判断target是否是元素编号"""
        return target.isdigit()
    
    def _build_playwright_selector(self, element: DOMElementNode) -> List[str]:
        """
        根据DOM元素构建多个Playwright选择器选项
        返回按优先级排序的选择器列表
        """
        selectors = []
        
        # 1. 优先使用id
        if 'id' in element.attributes and element.attributes['id']:
            selectors.append(f"#{element.attributes['id']}")
        
        # 2. 使用name属性
        if 'name' in element.attributes and element.attributes['name']:
            selectors.append(f"[name='{element.attributes['name']}']")
        
        # 3. 使用data-testid
        if 'data-testid' in element.attributes:
            selectors.append(f"[data-testid='{element.attributes['data-testid']}']")
        
        # 4. 使用class (取第一个class)
        if 'class' in element.attributes and element.attributes['class']:
            first_class = element.attributes['class'].split()[0]
            selectors.append(f".{first_class}")
        
        # 5. 使用xpath
        if element.xpath:
            selectors.append(f"xpath={element.xpath}")
        
        # 6. 基于属性的选择器
        for attr, value in element.attributes.items():
            if attr not in ['class', 'id', 'name', 'data-testid'] and value:
                selectors.append(f"[{attr}='{value}']")
        
        # 7. 最后使用标签名（最不精确）
        selectors.append(element.tag_name)
        
        return selectors
    
    def _get_element_text(self, element: DOMElementNode) -> str:
        """获取元素的文本内容"""
        text_parts = []
        
        def extract_text(node):
            if isinstance(node, DOMTextNode):
                text_parts.append(node.text.strip())
            elif isinstance(node, DOMElementNode):
                for child in node.children:
                    extract_text(child)
        
        extract_text(element)
        return " ".join(filter(None, text_parts))
    
    def _register_default_actions(self):
        """注册所有默认的web操作"""
        
        @self.registry.action(
            '点击页面元素，target可以是编号(如"8")、xpath或文本',
            param_model=ClickAction
        )
        async def click_element(params: ClickAction):
            current_page = self.get_current_page()
            if not current_page:
                return ActionResult(success=False, error="没有可用页面")
            
            # 记录操作前的状态
            old_page_count = len(self.context.pages)
            old_url = current_page.url
            
            try:
                success = await self._try_click_element(current_page, params.target)
                if success:
                    # 检测页面变化
                    page_changed, new_url = await self._detect_and_switch_page(old_page_count, old_url)
                    
                    msg = f"🖱️ 成功点击: {params.target}"
                    if page_changed:
                        msg += f" (页面已切换到: {new_url})"
                    
                    logger.info(msg)
                    return ActionResult(
                        success=True, 
                        message=msg, 
                        extracted_content=msg,
                        page_changed=page_changed,
                        new_page_url=new_url
                    )
                else:
                    return ActionResult(success=False, error=f"无法定位或点击元素: {params.target}")
            except Exception as e:
                return ActionResult(success=False, error=f"点击失败: {str(e)}")
        
        @self.registry.action(
            '在输入框中输入文本，target可以是编号(如"8")或其他定位器',
            param_model=InputAction
        )
        async def input_text(params: InputAction):
            current_page = self.get_current_page()
            if not current_page:
                return ActionResult(success=False, error="没有可用页面")
            
            try:
                success = await self._try_input_text(current_page, params.target, params.content)
                if success:
                    msg = f"⌨️ 成功输入到 {params.target}: {params.content}"
                    logger.info(msg)
                    return ActionResult(success=True, message=msg, extracted_content=msg)
                else:
                    return ActionResult(success=False, error=f"无法找到输入框: {params.target}")
            except Exception as e:
                return ActionResult(success=False, error=f"输入失败: {str(e)}")
        
        @self.registry.action(
            '选择下拉框选项，target是下拉框的编号或定位器，option是要选择的选项文本',
            param_model=SelectAction
        )
        async def select_option(params: SelectAction):
            current_page = self.get_current_page()
            if not current_page:
                return ActionResult(success=False, error="没有可用页面")
            
            try:
                success = await self._try_select_option(current_page, params.target, params.option)
                if success:
                    msg = f"🔽 成功选择 {params.target} 的选项: {params.option}"
                    logger.info(msg)
                    return ActionResult(success=True, message=msg, extracted_content=msg)
                else:
                    return ActionResult(success=False, error=f"无法选择选项: {params.target} -> {params.option}")
            except Exception as e:
                return ActionResult(success=False, error=f"选择失败: {str(e)}")
        
        @self.registry.action(
            '导航到指定URL',
            param_model=NavigateAction
        )
        async def navigate(params: NavigateAction):
            current_page = self.get_current_page()
            if not current_page:
                return ActionResult(success=False, error="没有可用页面")
            
            old_url = current_page.url
            
            try:
                await current_page.goto(params.url)
                await current_page.wait_for_load_state("domcontentloaded", timeout=10000)
                
                msg = f"🔗 导航到: {params.url}"
                logger.info(msg)
                return ActionResult(
                    success=True, 
                    message=msg, 
                    extracted_content=msg,
                    page_changed=True,
                    new_page_url=params.url
                )
            except Exception as e:
                return ActionResult(success=False, error=f"导航失败: {str(e)}")
        
        @self.registry.action(
            '等待指定时间',
            param_model=WaitAction
        )
        async def wait(params: WaitAction):
            try:
                await asyncio.sleep(params.seconds)
                msg = f"🕒 等待 {params.seconds} 秒"
                logger.info(msg)
                return ActionResult(success=True, message=msg, extracted_content=msg)
            except Exception as e:
                return ActionResult(success=False, error=f"等待失败: {str(e)}")
        
        @self.registry.action(
            '滚动页面，direction为up/down，distance为滚动距离',
            param_model=ScrollAction
        )
        async def scroll(params: ScrollAction):
            current_page = self.get_current_page()
            if not current_page:
                return ActionResult(success=False, error="没有可用页面")
            
            try:
                distance = params.distance if params.direction == "down" else -params.distance
                await current_page.evaluate(f"window.scrollBy(0, {distance})")
                msg = f"🔍 滚动 {params.direction} {abs(distance)}px"
                logger.info(msg)
                return ActionResult(success=True, message=msg, extracted_content=msg)
            except Exception as e:
                return ActionResult(success=False, error=f"滚动失败: {str(e)}")
    
    async def _try_click_element(self, page: Page, target: str) -> bool:
        """尝试不同方式点击元素"""
        # 优先检查是否是编号
        if self._is_element_index(target):
            index = int(target)
            element = self.get_element_by_index(index)
            if element:
                # 检查元素是否可见
                if not element.is_visible:
                    logger.warning(f"元素 {index} 不可见")
                    # 不直接返回False，尝试点击看看
                
                selectors = self._build_playwright_selector(element)
                for selector in selectors:
                    try:
                        locator = page.locator(selector)
                        if await locator.count() > 0:
                            await locator.first.click()
                            logger.debug(f"通过编号 {index} 点击成功，选择器: {selector}")
                            return True
                    except Exception as e:
                        logger.debug(f"选择器 {selector} 点击失败: {e}")
                        continue
        
        # 检查是否是xpath
        element = self.get_element_by_xpath(target)
        if element:
            selectors = self._build_playwright_selector(element)
            for selector in selectors:
                try:
                    await page.locator(selector).first.click()
                    logger.debug(f"通过xpath点击成功，选择器: {selector}")
                    return True
                except:
                    continue
        
        # 备用策略 - 文本和通用选择器
        strategies = [
            lambda: page.locator(f"text={target}").first.click(),
            lambda: page.locator(target).first.click(),
            lambda: page.get_by_text(target).first.click(),
            lambda: page.get_by_role("button", name=target).click(),
            lambda: page.get_by_role("link", name=target).click(),
            lambda: page.locator(f"[title='{target}']").first.click(),
            lambda: page.locator(f"[alt='{target}']").first.click(),
        ]
        
        for strategy in strategies:
            try:
                await strategy()
                return True
            except:
                continue
        
        return False
    
    async def _try_input_text(self, page: Page, target: str, content: str) -> bool:
        """尝试不同方式输入文本"""
        # 优先检查是否是编号
        if self._is_element_index(target):
            index = int(target)
            element = self.get_element_by_index(index)
            if element:
                # 检查是否是输入元素
                if element.tag_name not in ['input', 'textarea']:
                    logger.warning(f"元素 {index} 不是输入元素: {element.tag_name}")
                    return False
                
                selectors = self._build_playwright_selector(element)
                for selector in selectors:
                    try:
                        locator = page.locator(selector)
                        if await locator.count() > 0:
                            await locator.first.fill(content)
                            logger.debug(f"通过编号 {index} 输入成功，选择器: {selector}")
                            return True
                    except Exception as e:
                        logger.debug(f"选择器 {selector} 输入失败: {e}")
                        continue
        
        # 检查是否是xpath
        element = self.get_element_by_xpath(target)
        if element:
            selectors = self._build_playwright_selector(element)
            for selector in selectors:
                try:
                    await page.locator(selector).first.fill(content)
                    return True
                except:
                    continue
        
        # 备用策略
        strategies = [
            lambda: page.locator(target).first.fill(content),
            lambda: page.get_by_placeholder(target).fill(content),
            lambda: page.get_by_label(target).fill(content),
            lambda: page.locator(f"input[name='{target}']").fill(content),
            lambda: page.locator(f"textarea[name='{target}']").fill(content),
        ]
        
        for strategy in strategies:
            try:
                await strategy()
                return True
            except:
                continue
        return False
    
    async def _try_select_option(self, page: Page, target: str, option: str) -> bool:
        """尝试选择下拉框选项"""
        # 优先检查是否是编号
        if self._is_element_index(target):
            index = int(target)
            element = self.get_element_by_index(index)
            if element:
                selectors = self._build_playwright_selector(element)
                for selector in selectors:
                    try:
                        # 尝试原生select
                        await page.locator(selector).first.select_option(label=option)
                        logger.debug(f"通过编号 {index} 选择成功，选择器: {selector}")
                        return True
                    except:
                        # 尝试点击下拉框再选择选项 (自定义下拉框)
                        try:
                            await page.locator(selector).first.click()
                            await asyncio.sleep(0.5)
                            await page.locator(f"text={option}").first.click()
                            return True
                        except Exception as e:
                            logger.debug(f"选择器 {selector} 选择失败: {e}")
                            continue
        
        # 备用策略
        strategies = [
            lambda: page.locator(target).first.select_option(label=option),
            lambda: page.get_by_label(target).select_option(label=option),
            lambda: self._custom_select_option(page, target, option),
        ]
        
        for strategy in strategies:
            try:
                await strategy()
                return True
            except:
                continue
        return False
    
    async def _custom_select_option(self, page: Page, target: str, option: str):
        """处理自定义下拉框"""
        await page.locator(target).first.click()
        await asyncio.sleep(0.5)
        await page.locator(f"text={option}").first.click()
    
    # 页面管理方法
    def switch_to_page(self, page_index: int) -> bool:
        """手动切换到指定页面"""
        if not self.context or not self.context.pages:
            return False
        
        if 0 <= page_index < len(self.context.pages):
            self.current_page_index = page_index
            current_page = self.get_current_page()
            logger.info(f"🔄 切换到页面 {page_index}: {current_page.url if current_page else 'Unknown'}")
            return True
        return False
    
    def get_page_info(self) -> Dict:
        """获取当前页面信息"""
        current_page = self.get_current_page()
        if not current_page:
            return {"error": "没有可用页面"}
        
        return {
            "current_page_index": self.current_page_index,
            "total_pages": len(self.context.pages) if self.context else 0,
            "current_url": current_page.url,
            "title": current_page.title() if hasattr(current_page, 'title') else "Unknown"
        }
    
    # 主要的操作接口
    async def operate(self, operation: str, target: str = "", content: str = "") -> ActionResult:
        """
        执行操作的主要入口
        :param operation: 操作类型 (click, input, search, navigate, wait, scroll, select)
        :param target: 对象/目标 (可以是编号、xpath或其他定位器)
        :param content: 内容
        """
        
        if operation == "click":
            params = ClickAction(target=target)
            return await self.registry.execute_action("click_element", params)
        
        elif operation == "input":
            if not content:
                return ActionResult(success=False, error="输入操作需要content参数")
            params = InputAction(target=target, content=content)
            return await self.registry.execute_action("input_text", params)
        
        elif operation == "select":
            if not content:
                return ActionResult(success=False, error="选择操作需要content参数")
            params = SelectAction(target=target, option=content)
            return await self.registry.execute_action("select_option", params)
        
        elif operation == "navigate":
            params = NavigateAction(url=target)
            return await self.registry.execute_action("navigate", params)
        
        elif operation == "wait":
            seconds = float(content) if content else 3.0
            params = WaitAction(seconds=seconds)
            return await self.registry.execute_action("wait", params)
        
        elif operation == "scroll":
            direction = target or "down"
            distance = int(content) if content else 500
            params = ScrollAction(direction=direction, distance=distance)
            return await self.registry.execute_action("scroll", params)
        
        else:
            return ActionResult(success=False, error=f"未知操作: {operation}")
    
    def parse_operation_string(self, operation_string: str) -> tuple:
        """解析[操作：，对象：，内容：]格式的字符串"""
        operation_string = operation_string.strip("[]")
        parts = operation_string.split("，")
        
        operation = ""
        target = ""
        content = ""
        
        for part in parts:
            part = part.strip()
            if part.startswith("操作："):
                operation = part.replace("操作：", "").strip()
            elif part.startswith("对象："):
                target = part.replace("对象：", "").strip()
            elif part.startswith("内容："):
                content = part.replace("内容：", "").strip()
        
        return operation, target, content
    
    async def execute_from_string(self, operation_string: str) -> ActionResult:
        """从字符串格式执行操作"""
        try:
            operation, target, content = self.parse_operation_string(operation_string)
            return await self.operate(operation, target, content)
        except Exception as e:
            return ActionResult(success=False, error=f"解析操作字符串失败: {str(e)}")


# 使用示例
async def example_usage():
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        
        # 创建controller并设置context
        controller = WebController()
        controller.set_context(context)
        
        # 假设你有DOMElementNode对象列表
        # controller.update_dom_elements(your_dom_elements_list)
        
        # 导航到页面
        await page.goto("https://example.com")
        
        # 查看页面信息
        page_info = controller.get_page_info()
        print(f"当前页面信息: {page_info}")
        
        # 执行操作 - 这些操作会自动跟踪页面变化
        operations = [
            "[操作：click，对象：登录链接，内容：]",      # 可能会导航到新页面
            "[操作：input，对象：8，内容：用户名]",      # 在新页面输入
            "[操作：click，对象：提交按钮，内容：]",      # 可能再次导航
        ]
        
        for op in operations:
            result = await controller.execute_from_string(op)
            print(f"执行 {op}:")
            print(f"  成功: {result.success}")
            print(f"  消息: {result.message}")
            if result.page_changed:
                print(f"  页面已切换到: {result.new_page_url}")
            if not result.success:
                print(f"  错误: {result.error}")
            print()
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(example_usage())