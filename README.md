# auto_ai_web
&emsp;**目前，初步完成了任务的操作，下一步需要做的是：1. 多模态大模型识别页面中的图片 2. 大模型理解页面中文本和输入框的相关性**
&emsp;首先，把任务拆分出来，欺骗模型让他回答第一步是什么，第二步是什么
&emsp;然后，需要根据多模态把标题和输入框结合起来，确定位置
&emsp;最后，输入考虑

他把消息存在了一个叫做message manager里面，browser和control完成了所有的网页操作

需要知道的是，他调用大模型的方式是self.llm.ainvoke(input_messages, output_format=self.AgentOutput)