import json
import requests
from dotenv import load_dotenv
import os # 添加os模块用于加载环境变量
load_dotenv()
from config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL

def call_deepseek_api(
    prompt: str,
    history: list = None,
    system_message: str = None,
    context: str = None,
    max_tokens: int = 2048
) -> str:
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }

    messages = []
    if system_message:
        messages.append({"role": "system", "content": system_message})
    messages.append({"role": "user", "content": prompt})

    if context:
        messages.append({
            "role": "system",
            "content": f"以下是界面相关的按钮，请结合信息回答\n{context}"
        })

    if history:
        messages.extend(history)

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "top_p": 0.9
    }

    try:
        response = requests.post(
            DEEPSEEK_API_URL,
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
