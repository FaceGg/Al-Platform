FROM cgr.dev/chainguard/wolfi-base:latest@sha256:31cfe087eb48bde827a6e0f607a12865f6f37d89093b95b324b9d5714e3cedab
USER 0
WORKDIR /app
RUN set -eu; \
    printf '%s\n' 'https://packages.wolfi.dev/os' > /etc/apk/repositories; \
    for attempt in 1 2 3; do \
        if apk add --no-cache \
            python-3.11=3.11.17-r3 \
            py3.11-pip=26.2.2-r2 \
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
# AE 可选依赖（技术方案 §6.1，二期 M5）：torch CPU 版不进主安装包——现场
# 按需启用。WITH_TORCH=1 时装 torch（AE 自编码器族随之可用）；默认 0，
# AE 族自动缺席（AlgorithmUnavailable，IF/OC-SVM 不受影响）。
# 安装源二选一：
#   a) 补件 wheel：torch + 依赖闭包 wheel 拷入 wheelhouse 后 build（纯离线，
#      优先）；依赖闭包下载命令见 packaging/README-UBUNTU.md「启用自编码器族」。
#   b) 在线兜底：--find-links 指向 PyTorch 官方 CPU wheel 目录（默认值；
#      PyPI 的 linux torch 默认是 CUDA 版，带 GB 级 nvidia 依赖链，绝不可用
#      默认 PyPI 源）。Dockerfile 源码刻意不写显式 index 切换参数
#      （离线构建纪律合同 test_ci_workflow；find-links 目录页为官方源）。
# 依赖链（filelock/sympy/networkx/jinja2/fsspec/typing-extensions）随安装
# 自动解析。
ARG WITH_TORCH=0
ARG TORCH_WHEEL_INDEX="https://download.pytorch.org/whl/cpu/torch/"
RUN --mount=type=bind,target=/wheels,source=wheelhouse \
    --mount=type=cache,target=/root/.cache/pip \
    set -eu; \
    if [ "$WITH_TORCH" != "1" ]; then \
        echo "WITH_TORCH=0: skip torch (AE family absent, IF/OC-SVM unaffected)"; \
        exit 0; \
    fi; \
    if ls /wheels/torch-* >/dev/null 2>&1; then \
        echo "torch addon wheel found: offline install"; \
        python3.11 -m pip install --no-index --find-links /wheels "torch==2.15.0"; \
    else \
        echo "torch addon wheel absent: online install from PyTorch CPU wheel index"; \
        python3.11 -m pip install --find-links "$TORCH_WHEEL_INDEX" \
            --retries 5 --timeout 120 "torch==2.15.0"; \
    fi; \
    python3.11 -c "import torch; print('torch', torch.__version__, 'ok')"
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
