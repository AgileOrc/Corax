"""Enterprise demo application behind the gateway: a document store.

It has no access control of its own: every request that reaches it was allowed by OPA at the
gateway. Without the gateway, anyone could read any document by changing the id in the URL (BOLA).
"""

import hashlib

from fastapi import FastAPI

app = FastAPI(title="enterprise demo app")
TOPICS = ["quarterly plan", "architecture notes", "budget review", "incident report", "roadmap"]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/documents/{document_id}")
def document(document_id: str) -> dict:
    digest = hashlib.sha256(document_id.encode()).digest()
    topic = TOPICS[digest[0] % len(TOPICS)]
    return {
        "document": document_id,
        "title": f"{topic.title()} {document_id}",
        "content": f"Contents of {document_id}: {topic}, revision {digest[1] % 9 + 1}.",
    }
