# Ragolex web interface. Build: docker build -t ragolex-web frontend
# Serves the built app with nginx and forwards /api, /docs and /openapi.json
# to the API, so the browser only ever talks to one origin.

# Build stage: install dependencies and build the static files.
FROM node:22-alpine AS build
WORKDIR /web
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build


# Final stage: nginx as an unprivileged user (UID 101), listening on 8080.
FROM nginxinc/nginx-unprivileged:1.27-alpine

# Where the API is reached; the defaults fit docker compose.
ENV API_UPSTREAM=http://app:8000 \
    NGINX_RESOLVER=127.0.0.11

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
