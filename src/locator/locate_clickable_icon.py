import json
from pathlib import Path

def extract_clickable_elements(page):
    """
    提取所有可交互（点击+输入）元素，返回原始列表（不去重）
    """
    js = """
    () => {
        const elements = document.querySelectorAll("*");
        return Array.from(elements).map(el => {
            const rect = el.getBoundingClientRect();
            const visible = rect.width > 0 && rect.height > 0;

            const tag = el.tagName.toLowerCase();
            const type = (el.getAttribute("type") || "").toLowerCase();
            const role = el.getAttribute("role") || "";
            const className = el.className || "";
            const style = window.getComputedStyle(el);

            // ---- 新增：基于 class 的启发式识别 ----
            const hasButtonLikeClass = /(btn|button|search|submit|clickable)/i.test(className);

            // ---- 更严格的判断：class-only 也要具备交互迹象 ----
            const likelyInteractiveByClass = hasButtonLikeClass && (
                style.cursor === "pointer" ||
                typeof el.onclick === "function"
            );

            const isClickable =
                tag === "a" ||
                tag === "button" ||
                ["button", "link"].includes(role) ||
                typeof el.onclick === "function" ||
                style.cursor === "pointer" ||
                el.getAttribute("tabindex") !== null ||
                (tag === "input" && ["button", "submit"].includes(type)) ||
                el.closest("button, a, [role='button'], [role='link']") ||
                likelyInteractiveByClass;  // <== 只在确有交互迹象时才保留 class-only

            const isInputable =
                (tag === "input" && ["text", "search"].includes(type)) ||
                tag === "textarea";

            const clickable = visible && (isClickable || isInputable);

            return {
                tag: tag,
                role: role,
                type: type,
                title: el.getAttribute("title"),
                text: (el.innerText || "").trim().slice(0, 50),
                class: className,
                clickable: clickable,
                xpath: (function(){
                    let xpath = '', node = el;
                    while (node && node.nodeType === 1) {
                        let index = 1;
                        let sibling = node.previousSibling;
                        while (sibling) {
                            if (sibling.nodeType === 1 && sibling.tagName === node.tagName) index++;
                            sibling = sibling.previousSibling;
                        }
                        xpath = '/' + node.tagName.toLowerCase() + '[' + index + ']' + xpath;
                        node = node.parentNode;
                    }
                    return xpath;
                })()
            };
        }).filter(e => e.clickable);
    }
    """
    return page.evaluate(js)

def filter_elements(elements):
    """
    !这个内容很麻烦，后续需要更改
    根据父子元素优选逻辑过滤无用元素。
    简单启发式：
        1. 如果父子元素 text/title 完全相同且父元素缺少可识别属性 → 保留子元素。
        2. 如果父子元素 class/role 完全相同 → 保留父元素。
        3. 其他情况父子都保留。
    """
    filtered = []
    seen_xpaths = set()

    for e in elements:
        parent_xpaths = {"/".join(e["xpath"].split("/")[:-1])}  # 父节点xpath
        keep = True

        for p in filtered:
            if p["xpath"] in parent_xpaths:
                # 判断父子关系
                same_text = (p["text"] == e["text"] and p["title"] == e["title"])
                same_class_role = (p["class"] == e["class"] and p["role"] == e["role"])

                if same_text and not p["text"] and not p["title"]:
                    # 父元素信息不足 → 用子元素替换父元素
                    filtered.remove(p)
                    seen_xpaths.discard(p["xpath"])
                elif same_class_role:
                    # 父子几乎相同 → 舍弃子元素
                    keep = False

        if keep and e["xpath"] not in seen_xpaths:
            filtered.append(e)
            seen_xpaths.add(e["xpath"])

    return filtered

def highlight_clickable_elements(page):
    """
    高亮所有被 extract_clickable_elements 判定为 clickable 的元素
    """
    js = """
    () => {
        const elements = document.querySelectorAll("*");
        elements.forEach(el => {
            const rect = el.getBoundingClientRect();
            const visible = rect.width > 0 && rect.height > 0;
            if (!visible) return;

            const tag = el.tagName.toLowerCase();
            const type = (el.getAttribute("type") || "").toLowerCase();
            const role = el.getAttribute("role") || "";
            const className = el.className || "";
            const style = window.getComputedStyle(el);

            const hasButtonLikeClass = /(btn|button|search|submit|clickable)/i.test(className);
            const likelyInteractiveByClass = hasButtonLikeClass && (
                style.cursor === "pointer" || typeof el.onclick === "function"
            );

            const isClickable =
                tag === "a" ||
                tag === "button" ||
                ["button", "link"].includes(role) ||
                typeof el.onclick === "function" ||
                style.cursor === "pointer" ||
                el.getAttribute("tabindex") !== null ||
                (tag === "input" && ["button", "submit"].includes(type)) ||
                el.closest("button, a, [role='button'], [role='link']") ||
                likelyInteractiveByClass;

            const isInputable =
                (tag === "input" && ["text", "search"].includes(type)) ||
                tag === "textarea";

            if (isClickable || isInputable) {
                el.style.outline = "2px solid " + (
                    isInputable ? "blue" :
                    likelyInteractiveByClass ? "orange" : "limegreen"
                );
                el.style.outlineOffset = "2px";
            }
        });
    }
    """
    page.evaluate(js)


def highlight_only_kept(page, elements):
    """只高亮最终保留下来的元素（绿=完整信息，黄=信息不足，蓝=输入框）"""
    js_code = f"""
    () => {{
        const elements = {json.dumps(elements)};
        elements.forEach((e, index) => {{
            const el = document.evaluate(e.xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (el) {{
                const rect = el.getBoundingClientRect();
                const color = e.tag === 'input' ? 'blue' : (e.text || e.title ? 'green' : 'yellow');
                const div = document.createElement('div');
                div.style.position = 'absolute';
                div.style.left = rect.left + window.scrollX + 'px';
                div.style.top = rect.top + window.scrollY + 'px';
                div.style.width = rect.width + 'px';
                div.style.height = rect.height + 'px';
                div.style.border = '2px solid ' + color;
                div.style.zIndex = 9999;
                div.style.pointerEvents = 'none';
                div.innerHTML = '<span style="background:' + color + '; color: white; font-size: 12px;">' + index + '</span>';
                document.body.appendChild(div);
            }}
        }});
    }}
    """
    page.evaluate(js_code)


def generate_playwright_script(elements, url):
    """
    根据最终保留的元素生成 Playwright 操作脚本
    优化策略：
    1. 输入框用 page.fill()，其余用 click()
    2. class-only 元素会加推断说明
    3. 注释中附带详细 JSON 信息，方便 AI 理解
    """
    script_lines = [
        "from playwright.sync_api import sync_playwright",
        "",
        "def run(playwright):",
        "    browser = playwright.chromium.launch(headless=False)",
        "    context = browser.new_context()",
        "    page = context.new_page()",
        f"    page.goto('{url}')",
        ""
    ]

    for i, e in enumerate(elements):
        locator = None
        role = e.get("role")
        text = e.get("text")
        title = e.get("title")
        type_ = e.get("type")
        class_name = e.get("class")
        tag = e.get("tag")

        # 1. 输入框：直接用 fill()
        if tag == "input" and type_ in ["text", "search"]:
            locator = f'page.locator("input.{class_name.split()[0]}").fill("示例搜索内容")'

        # 2. checkbox
        elif type_ == "checkbox" or role == "checkbox":
            locator = f'page.get_by_role("checkbox", name="{text or title or ""}").check()'

        # 3. 有文本：优先 get_by_text
        elif text:
            locator = f'page.get_by_text("{text}").click()'

        # 4. 有 title
        elif title:
            locator = f'page.get_by_title("{title}").click()'

        # 5. 有 role
        elif role:
            locator = f'page.get_by_role("{role}", name="{text or title or ""}").click()'

        # 6. class-only：保底用 class 定位
        elif class_name:
            first_class = class_name.split(" ")[0]
            locator = f'page.locator(".{first_class}").click()'

        else:
            continue  # 没有任何定位依据则跳过

        # 注释更详细：告诉 AI 这是哪种推测
        reason = []
        if tag == "input" and type_ in ["text", "search"]:
            reason.append("推测为输入框")
        elif not (text or title or role):
            reason.append("推测为 class-only 按钮，可能需进一步确认其功能")

        reason_str = f" | {'; '.join(reason)}" if reason else ""
        script_lines.append(f"    # [{i}] {e}{reason_str}")
        script_lines.append(f"    {locator}")

    script_lines += [
        "",
        "    context.close()",
        "    browser.close()",
        "",
        "with sync_playwright() as p:",
        "    run(p)"
    ]
    return "\n".join(script_lines)


def save_to_file(data, filename):
    path = Path(filename)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(data, (dict, list)):
            json.dump(data, f, ensure_ascii=False, indent=2)
        else:
            f.write(data)
    print(f"✅ 已保存到 {path.resolve()}")

def compress_json(elements):
    """
    精简并过滤元素：
    1. 只保留 type, text, role, title, class, tag
    2. 如果字段为空则不保留
    3. 如果全部字段都为空（只有 tag），直接丢弃
    """
    compressed = []
    for e in elements:
        new_e = {}
        for key in ["type", "text", "role", "title", "class", "tag"]:
            value = e.get(key)
            if value and str(value).strip():
                new_e[key] = value.strip() if isinstance(value, str) else value

        # 至少需要一个除 tag 外的字段，否则丢弃
        has_meaningful_info = any(k in new_e for k in ["type", "text", "role", "title", "class"])
        if has_meaningful_info:
            compressed.append(new_e)
    return compressed

def locate_clickable_icon(page):
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    all_elements = extract_clickable_elements(page)
    filtered_elements = filter_elements(all_elements)

    # 页面高亮显示最终元素
    highlight_clickable_elements(page)

    # 精简 JSON 并保存
    compressed = compress_json(filtered_elements)  # filtered_elements 是经过过滤保留的元素

    #highlight_only_kept(page, compressed)  # 高亮最终保留的元素
    save_to_file(compressed, "clickable_elements_compressed.json")
    return compressed
