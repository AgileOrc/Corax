# POST /risk    called by OPA (http.send) only after the policy allowed a request
# GET  /health  model info, for checks and the demo

# Run: CORAX_MODEL_DIR=output/exp-hard50 uvicorn main:app --app-dir ai-corax --port 8000


import logging
from contextlib import asynccontextmanager

from config import Settings
from fastapi import FastAPI
from pydantic import BaseModel, Field
from risk import RiskModel

log = logging.getLogger("ai_corax")


class RiskRequest(BaseModel):
    user: str = Field(min_length=1, max_length=256)
    object: str = Field(min_length=1, max_length=256)


class RiskResponse(BaseModel):
    risk: float | None  # None when the user or object is unknown; the policy decision stands
    high_risk: bool
    threshold: float
    reason: str | None = None


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
        }

    return app


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
app = create_app()
