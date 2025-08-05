from flask import Flask, request, jsonify
import requests
from bs4 import BeautifulSoup
from main import process_task
import uuid
import threading

app = Flask(__name__)
task_queue = {}
results = {}

# 任务处理线程函数
async def worker():
    while True:
        for task_id, task_data in list(task_queue.items()):
            if task_data['status'] == 'pending':
                try:
                    task_queue[task_id]['status'] = 'processing'
                    
                    # 执行核心任务处理
                    result = await process_task(task_data['url'], task_data['task'])
                    
                    # 存储结果
                    results[task_id] = {
                        'status': 'completed',
                        'result': result
                    }
                    del task_queue[task_id]
                    
                except Exception as e:
                    results[task_id] = {
                        'status': 'failed',
                        'error': str(e)
                    }
                    del task_queue[task_id]

# 启动后台工作线程
threading.Thread(target=worker, daemon=True).start()

# 路由定义
@app.route('/submit', methods=['POST'])
def submit_task():
    """提交新任务"""
    data = request.json
    if not data or 'url' not in data or 'task' not in data:
        return jsonify({'error': '缺少url或task参数'}), 400
    
    # 生成唯一任务ID
    task_id = str(uuid.uuid4())
    task_queue[task_id] = {
        'url': data['url'],
        'task': data['task'],
        'status': 'pending'
    }
    return jsonify({'task_id': task_id}), 202

@app.route('/status/<task_id>', methods=['GET'])
def check_status(task_id):
    """检查任务状态"""
    if task_id in task_queue:
        return jsonify({'status': task_queue[task_id]['status']})
    
    if task_id in results:
        return jsonify(results[task_id])
    
    return jsonify({'error': '任务ID不存在'}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, threaded=True)