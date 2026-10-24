# DeviceVault web tier: the built SPA served by nginx, proxying the API.
#   docker build -f docker/web.Dockerfile -t devicevault-web .

# The SPA is the same on every platform, so build it natively rather than emulated.
FROM --platform=$BUILDPLATFORM node:24-alpine AS build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
# Scripts run at build time below, once the source (quasar.config.ts) is present.
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund --ignore-scripts
COPY frontend ./
RUN npx quasar build

FROM nginx:1.30-alpine
# The release workflow adds version, revision and creation labels.
LABEL org.opencontainers.image.source=https://github.com/SlinkySoftware/DeviceVault \
      org.opencontainers.image.licenses=GPL-3.0-or-later \
      org.opencontainers.image.vendor="Slinky Software"
ENV DV_API_UPSTREAM=api:8000 \
    DV_RESOLVER=127.0.0.11
COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /frontend/dist/spa /usr/share/nginx/html
EXPOSE 8080
