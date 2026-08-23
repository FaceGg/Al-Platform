FROM cgr.dev/chainguard/wolfi-base:latest@sha256:bfcffaf1336b26a3fd33c8cb31a86a09324d2048420d7f49b983f323b0d33e8d
USER 0
WORKDIR /app
RUN set -eu; \
    printf '%s\n' 'https://packages.wolfi.dev/os' > /etc/apk/repositories; \
    for attempt in 1 2 3; do \
        if apk add --no-cache \
            python-3.11=3.11.16-r1 \
            py3.11-pip=26.2.1-r0 \
            postgresql-16-client=16.11-r0; then \
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
