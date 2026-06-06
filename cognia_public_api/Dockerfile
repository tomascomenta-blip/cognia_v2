FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ctransformers has pre-built Linux x86_64 wheels — no cmake/gcc needed
RUN pip install --no-cache-dir "ctransformers>=0.2.27" || echo "[WARNING] ctransformers not installed"

# llama-cpp-python: try pre-built CPU wheel; skip silently if unavailable
RUN pip install --no-cache-dir llama-cpp-python \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/ \
    || echo "[WARNING] llama-cpp-python not installed, ctransformers or numpy will be used"

COPY . .
ENV DATA_DIR=/data
RUN mkdir -p /data
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
