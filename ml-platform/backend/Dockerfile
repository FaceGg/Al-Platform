FROM python:3.11-slim
WORKDIR /app
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 --timeout 120 -r requirements.txt
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --create-home app
COPY . .
RUN mkdir -p data uploads /tmp/ml-platform && chown -R app:app data uploads /tmp/ml-platform

EXPOSE 8000
ENV MPLCONFIGDIR=/tmp/matplotlib
USER app
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
