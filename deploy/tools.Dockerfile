# The repository's scripts in a container, so the demo needs nothing but Docker (deploy/README.md):
#   prepare  scripts/demo_gateway.py prepare: the enterprise graph and the HGNN (CPU torch) -> output/
#   demo     scripts/demo_backend.py: the demo as a log; it reads Envoy's and OPA's logs with the
#            docker CLI, so that service mounts the Docker socket
# Build context: the repository root.
FROM docker:27.5.1-cli AS docker

FROM python:3.13-slim
COPY --from=docker /usr/local/bin/docker /usr/local/bin/docker
WORKDIR /corax
# the CPU build: the default index would add several GB of CUDA libraries the demo does not use
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY hgnn/requirements.txt hgnn/requirements.txt
COPY service/requirements.txt service/requirements.txt
RUN pip install --no-cache-dir -r hgnn/requirements.txt -r service/requirements.txt
COPY hgnn hgnn
COPY service service
COPY scripts scripts
COPY demo/data.json demo/data.json
ENTRYPOINT ["python"]
