import base64
import binascii
import json
import logging
from contextlib import asynccontextmanager

from appeals import AppealError, Appeals
from config import Settings
from fastapi import FastAPI, HTTPException, Request
from graph import GraphData
from pydantic import BaseModel, Field
from risk import RiskModel

log = logging.getLogger("ai_corax")

class RiskRequest(BaseModel):
    user: str = Field(min_length=1, max_length=256)
    object: str = Field(min_length=1, max_length=256)

class RiskResponse(BaseModel):
    risk: float | None
    high_risk: bool
    threshold: float
    reason: str | None = None

class AppealRequest(BaseModel):
    appeal_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    user: str = Field(min_length=1, max_length=256)
    object: str = Field(min_length=1, max_length=256)
    action: str = Field(default="read", pattern=r"^[A-Za-z0-9_.:-]{1,64}$")

class PickRequest(BaseModel):
    candidate: int = Field(ge=1)

# The admin who calls /appeals: the "sub" of the bearer token. OPA verified the token at the
# gateway before Envoy forwarded the request, so here it is only decoded.
def caller(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        return "unknown"
    try:
        payload = header[7:].split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return str(claims.get("sub", "unknown"))
    except (IndexError, ValueError, binascii.Error):
        return "unknown"

def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.model = RiskModel.load(settings.model_dir, settings.risk_threshold)
        log.info(
            "loaded %s: %d users, %d objects, risk threshold %.4f",
            settings.model_dir,
            len(app.state.model.users),
            len(app.state.model.objects),
            app.state.model.threshold,
        )
        # appeals need the graph that hgnn-job exports next to the embeddings
        app.state.appeals = None
        if (settings.model_dir / "graph.json").exists():
            graph = GraphData.load(settings.model_dir)
            app.state.appeals = Appeals(settings, app.state.model, graph)
        else:
            log.warning("%s has no graph.json: /appeals is off", settings.model_dir)
        yield

    app = FastAPI(title="ai-corax", lifespan=lifespan)

    @app.post("/risk")
    def risk(request: RiskRequest) -> RiskResponse:
        model: RiskModel = app.state.model
        result = model.risk(request.user, request.object)
        if result.risk is None:
            log.warning("no score for %s -> %s: %s", request.user, request.object, result.reason)
        else:
            log.info(
                "risk %s -> %s = %.4f%s",
                request.user,
                request.object,
                result.risk,
                " HIGH" if result.high_risk else "",
            )
        return RiskResponse(
            risk=result.risk,
            high_risk=result.high_risk,
            threshold=model.threshold,
            reason=result.reason,
        )

    @app.get("/health")
    def health() -> dict:
        model: RiskModel = app.state.model
        return {
            "status": "ok",
            "target_edge_type": model.metadata["target_edge_type"],
            "created_at": model.metadata.get("created_at"),
            "risk_threshold": model.threshold,
            "users": len(model.users),
            "objects": len(model.objects),
            "appeals": app.state.appeals is not None,
        }

    def appeal_call(action):
        appeals: Appeals | None = app.state.appeals
        if appeals is None:
            raise HTTPException(503, "appeals need graph.json in the model folder (hgnn-job)")
        try:
            return action(appeals)
        except AppealError as error:
            raise HTTPException(error.status, str(error)) from error

    @app.post("/appeals")
    def submit_appeal(body: AppealRequest, request: Request) -> dict:
        admin = caller(request)
        return appeal_call(
            lambda a: a.submit(body.appeal_id, body.user, body.object, body.action, admin)
        )

    @app.get("/appeals/{appeal_id}")
    def read_appeal(appeal_id: str) -> dict:
        return appeal_call(lambda a: a.get(appeal_id))

    @app.post("/appeals/{appeal_id}/pick")
    def pick_candidate(appeal_id: str, body: PickRequest, request: Request) -> dict:
        admin = caller(request)
        return appeal_call(lambda a: a.pick(appeal_id, body.candidate, admin))

    @app.post("/appeals/{appeal_id}/confirm")
    def confirm_appeal(appeal_id: str, request: Request) -> dict:
        admin = caller(request)
        return appeal_call(lambda a: a.confirm(appeal_id, admin))

    @app.post("/appeals/{appeal_id}/reject")
    def reject_appeal(appeal_id: str, request: Request) -> dict:
        admin = caller(request)
        return appeal_call(lambda a: a.reject(appeal_id, admin))

    return app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
app = create_app()
