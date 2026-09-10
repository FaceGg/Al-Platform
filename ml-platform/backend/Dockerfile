FROM python:3.11-slim-bookworm
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgomp1 postgresql-client \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --home-dir /home/app --no-create-home app
RUN python -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --retries 10 --timeout 120 -r requirements.txt
COPY . .
RUN mkdir -p /home/app data app/uploads /tmp/matplotlib /tmp/ml-platform \
    && chown -R app:app /home/app data app/uploads /tmp/matplotlib /tmp/ml-platform

EXPOSE 8000
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV HOME=/home/app
USER 1000:1000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
