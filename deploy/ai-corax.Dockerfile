# ai-corax (ai-corax/main.py). Build context: the repository root.
FROM openpolicyagent/opa:1.21.2-static AS opa

FROM python:3.13-slim
# opa validates every exception and generated rule before it is written (validate.py)
COPY --from=opa /opa /usr/local/bin/opa
WORKDIR /corax
COPY ai-corax/requirements.txt ai-corax/requirements.txt
RUN pip install --no-cache-dir -r ai-corax/requirements.txt
COPY ai-corax/*.py ai-corax/
EXPOSE 8000
# OPA loads GENERATED_DIR when it starts (it waits for this container to be healthy), so the folder
# must exist before the first appeal writes into it
CMD ["sh", "-c", "mkdir -p \"${GENERATED_DIR:-policies/generated}\" && exec uvicorn main:app --app-dir ai-corax --host 0.0.0.0 --port 8000"]
