import asyncio
import json
import logging
import re
from typing import Generic, TypeVar, Any, Dict, List, Optional, Union
from playwright.sync_api import Page, BrowserContext, Locator
from pydantic import BaseModel
from dataclasses import dataclass

logger = logging.getLogger(__name__)

Context = TypeVar('Context')

# 假设你的DOMElementNode和DOMTextNode类已经定义

def extract_json_from_response(response: str) -> tuple[str, str, list]:
    """
    从模型返回的字符串中提取thought、task和place
    假设返回格式为 {"thinking": "...", "task": "...", "box": {"左上角坐标": "(x1, y1)", "右下角坐标": "(x2, y2)"}}
    将box转换为长度为4的数组 [x1, y1, x2, y2]
    """
    try:
        # 首先尝试提取 ```json 代码块中的内容
        json_str = response.strip()
        
        # 检查是否包含代码块标记
        if "```json" in json_str:
            import re
            # 提取 ```json 和 ``` 之间的内容
            json_match = re.search(r'```json\s*\n?(.*?)\n?```', json_str, re.DOTALL)
            if json_match:
                json_str = json_match.group(1).strip()
        
        # 解析JSON
        data = json.loads(json_str)
        thought = data.get("thinking", "")
        task = data.get("task", "")
        box_data = data.get("box", {})
        
        # 解析坐标并转换为数组
        place = []
        if isinstance(box_data, dict):
            top_left = box_data.get("左上角坐标", "")
            bottom_right = box_data.get("右下角坐标", "")
            
            # 提取坐标值
            try:
                # 使用正则表达式提取坐标
                import re
                
                # 提取左上角坐标 (x1, y1)
                top_left_match = re.search(r'\(([\d.]+),\s*([\d.]+)\)', top_left)
                if top_left_match:
                    x1, y1 = float(top_left_match.group(1)), float(top_left_match.group(2))
                else:
                    x1, y1 = 0.0, 0.0
                
                # 提取右下角坐标 (x2, y2)
                bottom_right_match = re.search(r'\(([\d.]+),\s*([\d.]+)\)', bottom_right)
                if bottom_right_match:
                    x2, y2 = float(bottom_right_match.group(1)), float(bottom_right_match.group(2))
                else:
                    x2, y2 = 0.0, 0.0
                
                place = [x1, y1, x2, y2]
            except (ValueError, AttributeError) as e:
                logger.warning(f"解析坐标失败: {e}")
                place = [0.0, 0.0, 0.0, 0.0]
        else:
            place = [0.0, 0.0, 0.0, 0.0]
        
        return thought, task, place
    except json.JSONDecodeError:
        logger.error("无法解析模型返回的JSON格式")
        return "", "", [0.0, 0.0, 0.0, 0.0]

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

# <<< MODIFIED >>> - 使 scroll 功能更强大
class ScrollAction(BaseAction):
    direction: str = "down"
    # 新增 target，可以滚动页面或特定元素
    target: Optional[str] = None 
    # 使用 num_pages 代替 distance，对LLM更友好
    num_pages: float = 1.0  

# <<< MODIFIED >>> - Pydantic模型保持不变，但其实现会更强大
class SelectAction(BaseAction):
    target: str
    option: str  # 要选择的选项文本

# <<< NEW >>> - 为获取下拉框选项新增模型
class GetDropdownOptionsAction(BaseAction):
    target: str # 下拉框的编号或选择器

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

    def _ensure_target_exists(self, target: str) -> bool:
        """检查目标是否存在于 dom_elements 或 xpath_to_element 映射中"""
        if self._is_element_index(target):
            return int(target) in self.dom_elements
        else:
            return target in self.xpath_to_element

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
        if not self.context:
            return False, ""

        # 等待新页面最多 10 秒
        for _ in range(10):
            new_page_count = len(self.context.pages)
            if new_page_count > old_page_count:
                break
            await asyncio.sleep(1)

        new_page_count = len(self.context.pages)
        if new_page_count > old_page_count:
            new_page = self.context.pages[-1]
            try:
                await new_page.wait_for_load_state("domcontentloaded", timeout=5000)
                await new_page.wait_for_load_state("networkidle", timeout=5000)
            except:
                pass
            self.current_page_index = new_page_count - 1
            return True, new_page.url

        # 情况2：URL变了
        current_page = self.get_current_page()
        if current_page:
            try:
                await current_page.wait_for_load_state("domcontentloaded", timeout=5000)
                await current_page.wait_for_load_state("networkidle", timeout=5000)
                current_url = current_page.url
                if current_url != old_url:
                    return True, current_url
            except:
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
            '获取原生HTML下拉框(<select>)的所有选项。target是下拉框的编号或选择器。',
            param_model=GetDropdownOptionsAction
        )
        async def get_dropdown_options(params: GetDropdownOptionsAction):
            current_page = self.get_current_page()
            if not current_page:
                return ActionResult(success=False, error="没有可用页面")

            try:
                locator = await self._find_locator(current_page, params.target)
                if not locator:
                    return ActionResult(success=False, error=f"找不到元素: {params.target}")

                # 确认是 <select> 元素
                tag_name = await locator.evaluate('el => el.tagName.toLowerCase()')
                if tag_name != 'select':
                    msg = f"元素 {params.target} 是一个 <{tag_name}>, 而不是 <select>。请使用 'click' 打开它，然后点击你想要的选项。"
                    return ActionResult(success=False, error=msg, message=msg)
                
                # 执行JS获取所有选项
                options = await locator.evaluate('''
                    (select) => Array.from(select.options).map(opt => ({
                        text: opt.text,
                        value: opt.value,
                        index: opt.index
                    }))
                ''')

                if not options:
                    return ActionResult(success=True, message=f"下拉框 {params.target} 中没有找到选项。", extracted_content="无可用选项")

                # 格式化输出给AI
                formatted_options = []
                for opt in options:
                    # 使用json.dumps确保文本中的特殊字符(如引号)被正确处理
                    encoded_text = json.dumps(opt['text']) 
                    formatted_options.append(f"{opt['index']}: text={encoded_text}")

                msg = "可用选项:\n" + "\n".join(formatted_options)
                msg += "\n\n提示: 使用 'select_option' 动作和选项的 'text' 值来选择。"
                logger.info(f"🔍 成功获取下拉框 {params.target} 的选项。")
                return ActionResult(success=True, message=msg, extracted_content=msg)

            except Exception as e:
                return ActionResult(success=False, error=f"获取选项失败: {str(e)}")

        # <<< MODIFIED >>> - 增强 select_option 动作
        @self.registry.action(
            '选择下拉框的选项。对于原生下拉框，直接选择。对于自定义下拉框，会先尝试点击打开，再选择选项。target是下拉框的编号或选择器，option是要选择的选项文本。',
            param_model=SelectAction
        )
        async def select_option(params: SelectAction): # 函数名保持不变
            current_page = self.get_current_page()
            if not current_page:
                return ActionResult(success=False, error="没有可用页面")
            
            try:
                # _try_select_option 方法将被重构以处理两种情况
                useful,success  = await self._try_select_option(current_page, params.target, params.option)
                if not useful:
                    return ActionResult(success=False, error=f"需要等待下一轮再试")
                if success:
                    msg = f"✅ 成功在 {params.target} 中选择了选项: {params.option}"
                    logger.info(msg)
                    return ActionResult(success=True, message=msg, extracted_content=msg)
                else:
                    return ActionResult(success=False, error=f"无法选择选项: {params.target} -> {params.option}。请确认目标和选项文本是否正确，或尝试滚动。")
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
        
        @self.registry.action(
            '滚动页面或指定的元素容器。direction为up/down。如果提供了target(编号或选择器)，则滚动该元素内部；否则滚动整个页面。',
            param_model=ScrollAction
        )
        async def scroll(params: ScrollAction):
            current_page = self.get_current_page()
            if not current_page:
                return ActionResult(success=False, error="没有可用页面")

            try:
                # <<< MODIFIED LOGIC START >>>
                direction_multiplier = 1 if params.direction == "down" else -1
                scroll_target_msg = "页面"
                
                # 情况1: 如果指定了目标，则滚动元素内部
                if params.target:
                    locator = await self._find_locator(current_page, params.target)
                    if locator:
                        scroll_target_msg = f"元素 '{params.target}'"
                        
                        # 获取元素容器的可见高度 (clientHeight)，而不是整个元素的高度
                        container_height = await locator.evaluate('el => el.clientHeight')
                        
                        # 如果元素不可见或没有高度，给一个合理的默认值 (例如250px) 以免滚动0距离
                        if container_height == 0:
                            logger.warning(f"滚动目标 {params.target} 高度为0，使用默认滚动距离。")
                            container_height = 250
                        
                        # 计算滚动距离：基于目标元素自身的高度
                        dy = int(container_height * params.num_pages * direction_multiplier)
                        
                        # 使用JavaScript直接修改元素的scrollTop属性，这是最可靠的内部滚动方式
                        await locator.evaluate('(element, dy) => { element.scrollTop += dy; }', dy)
                    else:
                        return ActionResult(success=False, error=f"找不到滚动目标: {params.target}")

                # 情况2: 否则，滚动整个页面
                else:
                    window_height = await current_page.evaluate('() => window.innerHeight')
                    # 计算滚动距离：基于浏览器窗口的高度
                    dy = int(window_height * params.num_pages * direction_multiplier)
                    await current_page.evaluate(f'window.scrollBy(0, {dy})')
                # <<< MODIFIED LOGIC END >>>

                msg = f"🔍 成功将 {scroll_target_msg} 向{params.direction}滚动了 {params.num_pages} '页'的距离"
                logger.info(msg)
                return ActionResult(success=True, message=msg, extracted_content=msg)
            except Exception as e:
                return ActionResult(success=False, error=f"滚动失败: {str(e)}")
                
    async def _find_locator(self, page: Page, target: str) -> Optional[Locator]:
        """根据target（编号、xpath或选择器）找到Playwright的Locator"""
        # 1. 尝试编号
        if self._is_element_index(target):
            index = int(target)
            element_node = self.get_element_by_index(index)
            if element_node and element_node.xpath:
                # 使用xpath最可靠
                return page.locator(f"xpath={element_node.xpath}")
        
        # 2. 尝试将target作为选择器
        try:
            locator = page.locator(target)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass

        # 3. 尝试文本
        try:
            locator = page.get_by_text(target, exact=True)
            if await locator.count() > 0:
                return locator.first
        except Exception:
            pass
            
        return None
    
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

    async def _try_select_option(self, page: Page, target: str, option: str) -> Dict[bool, bool]:
        """
        尝试用多种策略选择下拉选项：
        1. 原生<select>选择。
        2. 自定义下拉框：点击打开 -> 点击选项。
        """
        locator = await self._find_locator(page, target)
        if not locator:
            logger.warning(f"选择选项失败：找不到目标元素 '{target}'")
            return True,False

        # --- 策略1: 尝试作为原生 <select> 元素处理 ---
        try:
            # 使用 `label` 参数，这是最稳健的方式
            await locator.select_option(label=option, timeout=2000) # 短超时
            logger.info(f"成功使用原生select方式选择了 '{option}'")
            return True,True
        except Exception:
            logger.debug(f"原生select方式失败，将尝试自定义下拉框策略。")

        # --- 策略2: 尝试作为自定义下拉框处理 (点击 -> 等待 -> 点击) ---
        try:
            # 步骤 A: 点击目标元素以展开选项
            await locator.click()
            # 等待一小段时间让UI响应，比如选项列表出现
            await asyncio.sleep(0.5)
            return False,False
            # 步骤 B: 在整个页面中查找并点击出现的选项
            # 使用更精确的定位器，比如role="option"或直接按文本
            # 正则表达式 `^${...}$` 用于全词匹配，防止选中 "Option A" 时误选 "Option ABC"
            '''option_text_pattern = f"^{re.escape(option)}$"
            option_locator = page.get_by_role("option", name=re.compile(option_text_pattern))
            
            # 如果按角色找不到，回退到按文本查找
            if await option_locator.count() == 0:
                option_locator = page.get_by_text(option_text_pattern, exact=True)

            if await option_locator.count() > 0:
                await option_locator.first.click()
                logger.info(f"成功使用自定义下拉框方式点击了选项 '{option}'")
                return True
            else:
                logger.warning(f"点击了 '{target}' 后，未能找到文本为 '{option}' 的可见选项。可能需要滚动。")
                return False'''
        except Exception as e:
            logger.error(f"自定义下拉框选择策略失败: {e}")
            return False,False

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
        if operation == "done":
            return ActionResult(success=True, message="操作完成", is_done=True)
        
        if operation in ["click", "input", "select", "get_dropdown_options", "scroll"] and target:
        # 如果提供了目标，强制要求它存在
            if not self._ensure_target_exists(target):
                return ActionResult(success=False, error=f"未找到目标对象: {target}")

        if operation == "click":
            params = ClickAction(target=target)
            return await self.registry.execute_action("click_element", params)
        
        elif operation == "input":
            params = InputAction(target=target, content=content)
            return await self.registry.execute_action("input_text", params)
        
        # <<< NEW >>>
        elif operation == "get_dropdown_options":
            params = GetDropdownOptionsAction(target=target)
            return await self.registry.execute_action("get_dropdown_options", params)
            
        elif operation == "select":
            params = SelectAction(target=target, option=content) # option在content里
            return await self.registry.execute_action("select_option", params)
        
        elif operation == "navigate":
            params = NavigateAction(url=target)
            return await self.registry.execute_action("navigate", params)
        
        elif operation == "wait":
            seconds = float(content) if content and content.isdigit() else 3.0
            params = WaitAction(seconds=seconds)
            return await self.registry.execute_action("wait", params)
        
        # <<< MODIFIED >>>
        elif operation == "scroll":
            # 格式: scroll [target] [direction] [num_pages]
            # 例如: scroll "" "down 0.5" -> 滚动页面
            #       scroll "13" "down 2" -> 滚动元素13
            parts = content.split()
            direction = "down"
            num_pages = 1.0

            # 从content中解析方向和页数
            if len(parts) > 0 and parts[0].lower() in ["up", "down"]:
                direction = parts.pop(0).lower()
            
            if len(parts) > 0:
                try:
                    num_pages = float(parts[0])
                except (ValueError, IndexError):
                    pass # 如果解析失败，使用默认值

            # 注意：target 是从独立的 target 参数传入的
            params = ScrollAction(target=target, direction=direction, num_pages=num_pages)
            return await self.registry.execute_action("scroll", params)

        # <<< DELETED >>>
        # elif operation == "scroll_select": ...

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
    
    async def scroll_and_select_in_select2(self, select2_target: str, option_text: str, max_scroll_attempts: int = 10) -> ActionResult:
        """
        在Select2下拉框中滚动并选择指定选项的便捷方法
        :param select2_target: Select2下拉框的目标选择器或编号
        :param option_text: 要选择的选项文本
        :param max_scroll_attempts: 最大滚动尝试次数
        """
        current_page = self.get_current_page()
        if not current_page:
            return ActionResult(success=False, error="没有可用页面")
        
        try:
            # 首先尝试直接选择，如果选项已经可见
            try:
                option_locator = current_page.locator(f'.select2-results__option:has-text("{option_text}")')
                if await option_locator.count() > 0:
                    await option_locator.first.click()
                    msg = f"🎯 直接选择Select2选项成功: {option_text}"
                    logger.info(msg)
                    return ActionResult(success=True, message=msg, extracted_content=msg)
            except:
                pass
            
            # 如果直接选择失败，开始滚动搜索
            for attempt in range(max_scroll_attempts):
                # 滚动3次
                scroll_result = await self.operate("scroll_select", select2_target, "down 3")
                if not scroll_result.success:
                    logger.warning(f"滚动尝试 {attempt + 1} 失败: {scroll_result.error}")
                    continue
                
                await asyncio.sleep(0.3)  # 等待选项渲染
                
                # 再次尝试选择选项
                try:
                    option_locator = current_page.locator(f'.select2-results__option:has-text("{option_text}")')
                    if await option_locator.count() > 0:
                        await option_locator.first.click()
                        msg = f"🎯 滚动后选择Select2选项成功: {option_text} (滚动{attempt + 1}次)"
                        logger.info(msg)
                        return ActionResult(success=True, message=msg, extracted_content=msg)
                except Exception as e:
                    logger.debug(f"选择尝试失败: {e}")
                    continue
            
            # 如果向下滚动没找到，尝试向上滚动
            for attempt in range(max_scroll_attempts // 2):
                scroll_result = await self.operate("scroll_select", select2_target, "up 5")
                if not scroll_result.success:
                    continue
                
                await asyncio.sleep(0.3)
                
                try:
                    option_locator = current_page.locator(f'.select2-results__option:has-text("{option_text}")')
                    if await option_locator.count() > 0:
                        await option_locator.first.click()
                        msg = f"🎯 向上滚动后选择Select2选项成功: {option_text}"
                        logger.info(msg)
                        return ActionResult(success=True, message=msg, extracted_content=msg)
                except:
                    continue
            
            return ActionResult(success=False, error=f"经过多次滚动尝试，未能找到选项: {option_text}")
            
        except Exception as e:
            return ActionResult(success=False, error=f"Select2滚动选择失败: {str(e)}")


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
            "[操作：click，对象：登录链接，内容：]",                    # 可能会导航到新页面
            "[操作：input，对象：8，内容：用户名]",                    # 在新页面输入
            "[操作：click，对象：.select2-selection，内容：]",        # 打开Select2下拉框
            "[操作：scroll_select，对象：.select2-results__options，内容：down 5]", # 滚动Select2选项向下5次
            "[操作：select，对象：10，内容：2010]",                   # 选择年份2010
            "[操作：click，对象：提交按钮，内容：]",                   # 可能再次导航
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