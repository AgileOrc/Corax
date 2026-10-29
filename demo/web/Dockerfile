# The document app's web frontend: React and Tailwind, built with Vite, served by nginx behind Envoy
# (deploy/envoy.yaml routes "/" and "/assets/" here without the Corax check; every API call the
# page makes goes through Envoy -> OPA like any other client's).
FROM node:22.17.1-alpine AS build
WORKDIR /web
# the exact versions of package-lock.json
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html vite.config.js ./
COPY public public
COPY src src
RUN npm test && npm run build

FROM nginx:1.27.3-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist/ /usr/share/nginx/html/
