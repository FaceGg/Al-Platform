FROM node:20-alpine AS build
WORKDIR /app
# npm registry mirror for China-network builds; override with
# --build-arg NPM_REGISTRY=https://registry.npmjs.org if needed.
ARG NPM_REGISTRY=https://registry.npmmirror.com
COPY package*.json ./
# npm ci downloads tarballs from the URLs recorded in package-lock.json
# (registry.npmjs.org), which the --registry flag does not override. Rewrite
# them to the mirror host inside the image only; the repo lockfile is untouched.
RUN sed -i "s#https://registry.npmjs.org/#${NPM_REGISTRY}/#g" package-lock.json \
    && npm ci --include=dev --audit=false --registry=${NPM_REGISTRY}
COPY . .
RUN npx vite build

FROM nginx:stable-alpine
COPY --from=build /app/dist /usr/share/nginx/html
# index.html must revalidate on every load, otherwise browsers heuristically
# cache it and keep booting a stale bundle after deploys (hashed assets cache fine).
# client_max_body_size/proxy timeouts must match the edge nginx (500M/300s+):
# without them this interior proxy rejects large dataset uploads with 413/504
# before the request ever reaches the backend.
# resolver+变量 proxy_pass：静态 proxy_pass 在启动时解析一次 backend 地址并
# 永久缓存——backend 容器滚动重建换 IP 后本代理全量 /api 502（实测踩坑）。
# Docker 内嵌 DNS（127.0.0.11）按 valid 周期重解析，容器换 IP 自动跟上。
RUN echo 'server { listen 80; resolver 127.0.0.11 valid=10s ipv6=off; root /usr/share/nginx/html; index index.html; client_max_body_size 500M; proxy_read_timeout 600s; proxy_send_timeout 600s; location /assets/ { add_header Cache-Control "public, max-age=31536000, immutable"; try_files $uri =404; } location / { add_header Cache-Control "no-cache"; try_files $uri $uri/ /index.html; } location /api/ { set $backend_upstream backend:8000; proxy_pass http://$backend_upstream; proxy_set_header Host $host; } location /ws/ { set $backend_upstream backend:8000; proxy_pass http://$backend_upstream; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; } }' > /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
