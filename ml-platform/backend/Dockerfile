FROM cgr.dev/chainguard/wolfi-base:latest@sha256:31cfe087eb48bde827a6e0f607a12865f6f37d89093b95b324b9d5714e3cedab
USER 0
WORKDIR /app
RUN set -eu; \
    printf '%s\n' 'https://packages.wolfi.dev/os' > /etc/apk/repositories; \
    for attempt in 1 2 3; do \
        if apk add --no-cache \
            python-3.11=3.11.17-r3 \
            py3.11-pip=26.2.1-r4 \
            postgresql-16-client=16.14-r1 \
            glibc \
            libgomp; then \
            exit 0; \
        fi; \
        if [ "$attempt" -eq 3 ]; then \
            exit 1; \
        fi; \
        sleep "$attempt"; \
    done
RUN python3.11 -c "import sqlite3"
RUN addgroup -S -g 1000 app && adduser -S -D -H -h /home/app -u 1000 -G app app
COPY requirements.txt .
# Keep the CPU image free of XGBoost's Linux NCCL dependency.
# wheelhouse 非空（本机自持 144+ 轮子）→ 纯离线安装，网络好坏不影响构建
# （2026-10-28 事故：代理宕机 + PyPI 82KB/s，131MB 下载阻塞部署 1 小时）；
# wheelhouse 为空（CI/全新 checkout，.keep 占位）→ 走网络安装（CI 网络快）。
# 维护约定：requirements 升版本必须同步 pip download 补 wheelhouse 对应 wheel。
RUN --mount=type=bind,target=/wheels,source=wheelhouse \
    --mount=type=cache,target=/root/.cache/pip \
    set -eu; \
    if [ -n "$(ls /wheels 2>/dev/null | head -1)" ]; then \
        echo "wheelhouse populated: offline install"; \
        INDEX_FLAGS="--no-index"; \
    else \
        echo "wheelhouse empty: online install"; \
        INDEX_FLAGS=""; \
    fi; \
    python3.11 -m pip install $INDEX_FLAGS --find-links /wheels --no-deps --retries 10 --resume-retries 20 --timeout 120 \
        "xgboost==3.2.*" "catboost==1.2.*"; \
    sed '/^xgboost==/d; /^catboost==/d' requirements.txt > /tmp/requirements-without-boost.txt; \
    python3.11 -m pip install $INDEX_FLAGS --find-links /wheels --retries 10 --resume-retries 20 --timeout 120 \
        graphviz plotly six \
        -r /tmp/requirements-without-boost.txt
COPY . .
RUN mkdir -p /home/app data app/uploads /var/lib/tensorboard/runs \
    /var/lib/ml-platform/inference-cache /tmp/ml-platform /app/artifact_store \
    /data/python-script-venv \
    && chown -R app:app /home/app data app/uploads /var/lib/tensorboard \
    /var/lib/ml-platform /tmp/ml-platform /app/artifact_store /data

EXPOSE 8000
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV HOME=/home/app
USER 1000:1000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
