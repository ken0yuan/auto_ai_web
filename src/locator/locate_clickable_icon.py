"""
Playwright AI 辅助操作脚本生成器（去重+页面标注版）
功能：
1. 扫描页面所有可点击元素。
2. 根据父子元素的优选逻辑过滤无用元素。
3. 在页面上框出最终保留的元素，并显示序号。
4. 保存 JSON 和自动生成的脚本到本地。
"""

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

def extract_clickable_elements(page):
    """
    提取所有可点击元素，返回原始列表（不去重）
    """
    js = """
    () => {
        const elements = document.querySelectorAll("*");
        return Array.from(elements).map(el => {
            const rect = el.getBoundingClientRect();
            const clickable = (
                el.tagName === "A" || el.tagName === "BUTTON" ||
                typeof el.onclick === "function" ||
                window.getComputedStyle(el).cursor === "pointer" ||
                el.getAttribute("role") === "button" ||
                el.getAttribute("role") === "link"
            ) && rect.width > 0 && rect.height > 0;

            return {
                tag: el.tagName.toLowerCase(),
                role: el.getAttribute("role"),
                type: el.getAttribute("type"),
                title: el.getAttribute("title"),
                text: (el.innerText || "").trim().slice(0, 50),
                class: el.className,
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

def highlight_elements(page, elements):
    """
    在页面上高亮显示最终保留的元素
    """
    js_code = f"""
    () => {{
        const elements = {json.dumps(elements)};
        elements.forEach((e, index) => {{
            const el = document.evaluate(e.xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (el) {{
                const rect = el.getBoundingClientRect();
                const div = document.createElement('div');
                div.style.position = 'absolute';
                div.style.left = rect.left + window.scrollX + 'px';
                div.style.top = rect.top + window.scrollY + 'px';
                div.style.width = rect.width + 'px';
                div.style.height = rect.height + 'px';
                div.style.border = '2px solid red';
                div.style.zIndex = 9999;
                div.style.pointerEvents = 'none';
                div.innerHTML = '<span style="background: red; color: white; font-size: 12px;">' + index + '</span>';
                document.body.appendChild(div);
            }}
        }});
    }}
    """
    page.evaluate(js_code)

def highlight_only_kept(page, elements):
    """只高亮最终保留下来的元素（绿=完整信息，黄=信息不足但仍保留）"""
    js_code = f"""
    () => {{
        const elements = {json.dumps(elements)};
        elements.forEach((e, index) => {{
            const el = document.evaluate(e.xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (el) {{
                const rect = el.getBoundingClientRect();
                const div = document.createElement('div');
                div.style.position = 'absolute';
                div.style.left = rect.left + window.scrollX + 'px';
                div.style.top = rect.top + window.scrollY + 'px';
                div.style.width = rect.width + 'px';
                div.style.height = rect.height + 'px';
                div.style.border = '2px solid ' + (e.text || e.title ? 'green' : 'yellow');
                div.style.zIndex = 9999;
                div.style.pointerEvents = 'none';
                div.innerHTML = '<span style="background:' + (e.text || e.title ? 'green' : 'yellow') + '; color: white; font-size: 12px;">' + index + '</span>';
                document.body.appendChild(div);
            }}
        }});
    }}
    """
    page.evaluate(js_code)

def generate_playwright_script(elements, url):
    """
    根据最终保留的元素生成 Playwright 操作脚本
    按优先级使用字段：text > title > role+name > class
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

        # 按优先级生成定位器
        if type_ == "checkbox" or role == "checkbox":
            locator = f'page.get_by_role("checkbox", name="{text or title}").check()'
        elif text:
            locator = f'page.get_by_text("{text}").click()'
        elif title:
            locator = f'page.get_by_title("{title}").click()'
        elif role:
            locator = f'page.get_by_role("{role}", name="{text or title}").click()'
        elif class_name:
            locator = f'page.locator(".{class_name.split(" ")[0]}").click()'
        else:
            continue  # 没有可用字段就跳过

        script_lines.append(f"    # [{i}] {e}")
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
    精简元素列表：
    1. 只保留 type, text, role, title, class
    2. 如果字段为空则直接不保留该字段
    """
    compressed = []
    for e in elements:
        new_e = {}
        for key in ["type", "text", "role", "title", "class"]:
            value = e.get(key)
            if value and str(value).strip():  # 非空才保留
                new_e[key] = value.strip() if isinstance(value, str) else value
        if new_e:  # 只添加非空的元素
            compressed.append(new_e)
    return compressed

def main():
    url = input("请输入需要分析的网页URL: ").strip()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url)

        print("正在扫描可点击元素...")
        all_elements = extract_clickable_elements(page)
        filtered_elements = filter_elements(all_elements)

        # 页面高亮显示最终元素
        highlight_elements(page, filtered_elements)

        # 精简 JSON 并保存
        compressed = compress_json(filtered_elements)  # filtered_elements 是经过过滤保留的元素
        
        #highlight_only_kept(page, compressed)  # 高亮最终保留的元素
        save_to_file(compressed, "clickable_elements_compressed.json")

        # 输出并保存 JSON
        print("\n=== 最终保留的元素 JSON ===")
        
        print(json.dumps(compressed, ensure_ascii=False, indent=2))

        # 自动生成并保存 Playwright 脚本
        print("\n=== AI 自动生成的 Playwright 脚本 ===")
        script = generate_playwright_script(compressed, url)
        print(script)
        save_to_file(script, "generated_script_filtered.py")

        input("页面已高亮显示元素，按回车后关闭浏览器...")
        context.close()
        browser.close()

if __name__ == "__main__":
    main()
