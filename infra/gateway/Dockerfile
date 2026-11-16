# Phase 5.3 -- the gateway becomes a custom image for the first time, baking
# the dashboard's static SPA build into the same nginx that already proxies
# the API. This is ADR-006's explicit design: "a static SPA bundle... served
# by the nginx gateway that already exists... no new production workload" --
# not a separate Node server, not a new deployed workload.
#
# Build context is the repo root (matching every other service's Dockerfile
# convention), so paths below are relative to that root, not to infra/gateway/.

FROM node:20-alpine AS build
WORKDIR /app
COPY apps/dashboard/package.json apps/dashboard/package-lock.json ./
RUN npm ci
COPY apps/dashboard/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY infra/gateway.nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8000
