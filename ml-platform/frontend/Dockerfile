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
RUN echo 'server { listen 80; root /usr/share/nginx/html; index index.html; location / { try_files $uri $uri/ /index.html; } location /api/ { proxy_pass http://backend:8000; proxy_set_header Host $host; } location /ws/ { proxy_pass http://backend:8000; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; } }' > /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://127.0.0.1/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
