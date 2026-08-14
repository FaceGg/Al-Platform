FROM cgr.dev/chainguard/wolfi-base:latest@sha256:30f03343947c7ae3581fda727a6e2aa7b8ce7009b7bfc2ab8d5c9483ace5812f
USER 0
WORKDIR /app
RUN set -eu; \
    for attempt in 1 2 3; do \
        if apk add --no-cache python-3.11=3.11.14-r0 py3.11-pip=25.3-r3; then \
            exit 0; \
        fi; \
        if [ "$attempt" -eq 3 ]; then \
            exit 1; \
        fi; \
        sleep "$attempt"; \
    done
RUN addgroup -S -g 1000 app && adduser -S -D -H -h /home/app -u 1000 -G app app
RUN python3.11 -m pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    python3.11 -m pip install --retries 10 --resume-retries 20 --timeout 120 -r requirements.txt
COPY . .
RUN mkdir -p /home/app data app/uploads /tmp/ml-platform \
    && chown -R app:app /home/app data app/uploads /tmp/ml-platform

EXPOSE 8000
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV HOME=/home/app
USER 1000:1000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
