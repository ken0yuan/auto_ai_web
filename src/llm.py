import json
import requests
from config import DEEPSEEK_MODEL, OPENROUTER_API_KEY, OPENROUTER_API_URL, QWEN_MODEL

def generate_opera(
    task: str,
    context: str = None,
    image_base64: list = None,
    max_tokens: int = 2048
) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    messages = []
    messages.append({"role": "system", "content":"你是一个任务完成大师，你需要完成的任务是{task}\n网页相关信息如下{context}\n，你需要返回的是一个json格式的完成的任务描述和操作，操作包含操作种类(包含click, input, search, navigate, wait, scroll, select)(如果需要翻页，只能进行翻页操作，不能有其他操作)，操作对象序号(只能是数字序号)和填写内容（如果不需要填写则为空）。返回示例如下['[任务描述：完成了名字的填写]','[操作：click，对象：登录链接，内容：]', '[操作：input，对象：8，内容：用户名]','[操作：click，对象：提交按钮，内容：]','[操作：scroll，对象：，内容：300]','[操作：wait，对象：，内容：10]']"})
    messages.append({"role": "user", "content": task})

    if context:
        messages.append({
            "role": "system",
            "content": f"以下是界面内可操作的元素，请结合信息回答\n{context}"
        })

    if image_base64:
        messages[1]["content"] = [
            {"type": "text", "text": task},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}}
        ]

    payload = {
        "model": QWEN_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "top_p": 0.9
    }

    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers=headers,
            data=json.dumps(payload),
            timeout=30
        )
        
        print("Status Code:", response.status_code)
        #print("Response Text:", response.text[:500])  # 只打印前500字避免太长
        
        if response.status_code == 200:
            try:
                result = response.json()
                return result['choices'][0]['message']['content'].strip()
            except json.JSONDecodeError:
                return "返回的内容不是合法的 JSON。"
        else:
            return f"API错误: {response.status_code} - {response.text}"

    except Exception as e:
        return f"调用API失败: {str(e)}"


def ui_analyzer(
        prompt: str,
        image_base64: list = None,
        system_message: str = None,
        history: list = None,
        max_tokens: int = 2048
) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    # ✅ 正确顺序：先加入历史
    history_text = ""
    if history:
        for h in history:
            if h["role"] == "user":
                history_text += f"\n- 已经完成的任务：{h['content']}"
            elif h["role"] == "assistant":
                history_text += f"\n- 已完成操作：{h['content']}"
    
    if system_message:
        system_message = system_message.replace("{history_text}", history_text).replace("{user_task}", prompt)

    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})

    # ✅ 再加入当前 user prompt
    if image_base64:
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}}
            ]
        })
    else:
        messages.append({"role": "user", "content": prompt})

    #print(messages)

    payload = {
        "model": QWEN_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "top_p": 0.9
    }

    try:
        response = requests.post(
            OPENROUTER_API_URL,
            headers=headers,
            data=json.dumps(payload),
            timeout=30
        )

        print("Status Code:", response.status_code)
        # print("Response Text:", response.text[:500])  # 只打印前500字避免太长

        if response.status_code == 200:
            try:
                result = response.json()
                return result['choices'][0]['message']['content'].strip()
            except json.JSONDecodeError:
                return "返回的内容不是合法的 JSON。"
        else:
            return f"API错误: {response.status_code} - {response.text}"

    except Exception as e:
        return f"调用API失败: {str(e)}"