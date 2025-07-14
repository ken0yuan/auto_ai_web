1. playwright.sync_api对应的基础操作
    1. 同步的api库，从其中调用sync_playwright  
    2. sync_playwright().start():返回值是启动的 playwright driver 进程Playwright类，设为p，这个进程可以在任务管理器中看到为node.exe，位置在安装playwright的地方。
    3. p.stop()，停止进程
    4. p.chromium.launch():启动浏览器，浏览器是chromium内核。返回对象是Browser类，以下是参数
        1. headless=False：显示浏览器页
        2. 选用自己的浏览器：executable_path=''
        3. 注意：浏览器需要对应内核，edge，Google，chromium对应chromium；Firefox对应firefox；webkit和safari对应webkit
    5. browser.new_page()
    6. page.goto("")：前往对应网址
    7. page.title()
    8. browser.close()
    9. 可以用with sync_playwright().start() as p:来作为一个小函数，自动启动进程停止进程
    10. page.wait_for_timeout(): 等待一会，单位毫秒，防止浏览器尚未加载就已经开始读。注意，不能使用time.sleep()，会破坏底层的异步架构。
    11. 命令行里可以进行自动化代码助手的工作，代码为playwright codegen，注意，由于playwright一般被下载在虚拟环境中，需要寻找对应位置，我的在D:\Anaconda3\envs\browser-use\Scripts\playwright.exe，这个工具会先开一个空白页面，然后你做的所有操作都会被他转化成对应的代码。无法提取输出
    12. context = browser.new_context(),这个context是对操作跟踪的用处，
        1. context.tracing.start(snapshots=True, sources=True, screenshots=True)启动跟踪
        2. context.tracing.stop(path="trace.zip")结束跟踪
        3. playwright show-trace trace.zip显示测试结果，参考视频
        4. 用于自动化测试
2. 定位
    首先是css选择器
    1. 中国
    2. 
3. 操作
4. 保存