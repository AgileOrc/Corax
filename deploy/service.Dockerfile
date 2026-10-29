# The Corax service (service/main.py): /risk and /corax/appeals. Build context: the repository root.
FROM openpolicyagent/opa:1.21.2-static AS opa

FROM python:3.13-slim
# opa validates every exception and generated rule before it is written (validate.py)
COPY --from=opa /opa /usr/local/bin/opa
WORKDIR /corax
COPY service/requirements.txt service/requirements.txt
RUN pip install --no-cache-dir -r service/requirements.txt
COPY service/*.py service/
EXPOSE 8000
# OPA loads GENERATED_DIR when it starts (it waits for this container to be healthy), so the folder
# must exist before the first appeal writes into it
CMD ["sh", "-c", "mkdir -p \"${GENERATED_DIR:-policies/generated}\" && exec uvicorn main:app --app-dir service --host 0.0.0.0 --port 8000"]
