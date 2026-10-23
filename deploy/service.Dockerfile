# corax-service: FastAPI (/risk, /corax/appeals) plus the opa binary it uses to validate generated Rego.
# Built from the repository root (see docker-compose.yml); .dockerignore keeps the context to service/.
FROM openpolicyagent/opa:1.21.2-static AS opa

FROM python:3.12.14-slim
COPY --from=opa /opa /usr/local/bin/opa
WORKDIR /app
COPY service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY service/ .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
