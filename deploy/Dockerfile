# 智能拍照学习助手 · API 容器
# 构建上下文是项目根目录：
#   docker build -f deploy/Dockerfile -t learnmate-api .
#
# 只装运行时依赖。OCR / PDF 那套（onnxruntime、opencv、pymupdf）
# 只在离线建库时用，镜像里不需要，否则光它们就 +500MB。

FROM python:3.12-slim

ENV TZ=Asia/Shanghai \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 依赖单独一层，改代码不会触发重装
COPY deploy/requirements-runtime.txt /tmp/req.txt
RUN pip install --no-cache-dir -r /tmp/req.txt && rm -f /tmp/req.txt

# 只拷后端；kb_images / uploads / dev.db 由 compose 挂载进来
COPY backend/ /app/

RUN mkdir -p /app/uploads

EXPOSE 8000

# 容器自愈：连续 3 次探测失败会被 compose 判为 unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import sys,urllib.request; \
sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3).status == 200 else 1)"

# 单 worker：SQLite 并发写有限，多进程只会更容易锁表
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
