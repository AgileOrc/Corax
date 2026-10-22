# deploy

Deployment files for running Corax in front of an application. Not built yet.

- `envoy.yaml`: Envoy sidecar with `ext_authz` to OPA, `failure_mode_allow: false`.
- `docker-compose.yml`: Envoy + OPA (with `opa-envoy-plugin`) + `corax-service`.
