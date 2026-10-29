# The document app's web frontend: static files, no build step, served by nginx behind Envoy
# (deploy/envoy.yaml routes "/" and "/assets/" here without the Corax check; every API call the
# page makes goes through Envoy -> OPA like any other client's).
FROM nginx:1.27.3-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
COPY assets/ /usr/share/nginx/html/assets/
