# fuckai — LLM 注入攻击测试台
FROM python:3.12-slim

WORKDIR /app

# 先装依赖（利用层缓存）；内嵌浏览器引擎需要 Chromium 运行库
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

# 拷贝代码与内置弹药库/资料
COPY fuckai/ fuckai/
COPY web/ web/
COPY datasets/ datasets/
COPY web.py config_example.yaml resources.yaml ./

EXPOSE 8001

CMD ["python", "web.py", "--host", "0.0.0.0", "--port", "8001"]
