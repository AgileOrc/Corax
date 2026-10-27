import logging
from contextlib import asynccontextmanager

from appeals import AppealError, AppealService
from auth import AdminAuth, AuthError
from config import Settings
from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from graph import GraphData
from pydantic import BaseModel, Field
from risk import RiskModel

log = logging.getLogger("corax.service")

class RiskRequest(BaseModel):
    user: str = Field(min_length=1, max_length=256)
    object: str = Field(min_length=1, max_length=256)
    # Sent by OPA so a use of access granted by an appeal is logged for the right rule.
    action: str | None = Field(default=None, max_length=128)

class UsageRequest(BaseModel):
    user: str = Field(min_length=1, max_length=256)
    object: str = Field(min_length=1, max_length=256)
    action: str | None = Field(default=None, max_length=128)

class RiskResponse(BaseModel):
    risk: float | None
    high_risk: bool
    threshold: float
    reason: str | None = None

class AppealRequest(BaseModel):
    user: str = Field(min_length=1, max_length=256)
    object: str = Field(min_length=1, max_length=256)
    action: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)

class ConfirmRequest(BaseModel):
    candidate: int | None = None
    acknowledge_scope: bool = False

class RevokeRequest(BaseModel):
    # Also remove the appellant's own exception, not only the rule.
    exception: bool = False

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
        app.state.appeals = None
        if (settings.model_dir / "graph.json").exists():
            graph = GraphData.load(settings.model_dir)
            app.state.appeals = AppealService(app.state.model, graph, settings)
        else:
            log.warning("no graph.json in %s: appeals are disabled", settings.model_dir)
        yield

    app = FastAPI(title="corax-service", lifespan=lifespan)

    app.state.auth = AdminAuth(settings.corax_config)

    @app.exception_handler(AuthError)
    def auth_error(_: Request, error: AuthError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else None
        return JSONResponse(status_code=error.status, content={"error": error.message}, headers=headers)

    def require_admin(authorization: str | None = Header(default=None)) -> str:
        return app.state.auth.authenticate(authorization)

    def require_user(authorization: str | None = Header(default=None)) -> str:
        return app.state.auth.authenticate_user(authorization)

    @app.exception_handler(AppealError)
    def appeal_error(_: Request, error: AppealError) -> JSONResponse:
        return JSONResponse(status_code=error.status, content={"error": error.message, **error.detail})

    def appeals() -> AppealService:
        if app.state.appeals is None:
            raise AppealError(503, "appeals are disabled: the model folder has no graph.json")
        return app.state.appeals

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
        # OPA calls /risk only after the policy allowed the request, so a low risk means it goes through.
        if not result.high_risk and app.state.appeals is not None:
            app.state.appeals.record_use(request.user, request.object, request.action, "rule")
        return RiskResponse(
            risk=result.risk,
            high_risk=result.high_risk,
            threshold=model.threshold,
            reason=result.reason,
        )

    # Internal like /risk: OPA calls it when an appeal exception allowed a request, which skips /risk.
    @app.post("/usage")
    def usage(request: UsageRequest) -> dict:
        if app.state.appeals is None:
            return {"logged": []}
        return {"logged": app.state.appeals.record_use(request.user, request.object, request.action, "exception")}

    @app.post("/corax/appeals", status_code=201)
    def create_appeal(body: AppealRequest, admin: str = Depends(require_admin)) -> dict:
        record = appeals().create(body.user, body.object, body.action, body.reason, admin)
        log.info("appeal %s by %s: %s -> %s (%s)", record["id"], admin, body.user, body.object, body.action)
        return record

    @app.get("/corax/appeals/{appeal_id}")
    def get_appeal(appeal_id: str, admin: str = Depends(require_admin)) -> dict:
        return appeals().get(appeal_id)

    @app.get("/corax/appeals/{appeal_id}/candidates/{candidate}")
    def preview_candidate(appeal_id: str, candidate: int, admin: str = Depends(require_admin)) -> dict:
        return appeals().preview(appeal_id, candidate)

    @app.post("/corax/appeals/{appeal_id}/confirm")
    def confirm_appeal(appeal_id: str, body: ConfirmRequest, admin: str = Depends(require_admin)) -> dict:
        record = appeals().confirm(appeal_id, body.candidate, body.acknowledge_scope, admin)
        log.info("appeal %s %s by %s", appeal_id, record["status"], admin)
        return record

    @app.get("/corax/rules")
    def list_rules(admin: str = Depends(require_admin)) -> list[dict]:
        return appeals().rules()

    # The user comes only from the verified token, never from the request, so nobody can read
    # another user's access.
    @app.get("/corax/me/access")
    def my_access(user: str = Depends(require_user)) -> dict:
        return {"user": user, "resources": appeals().access_of(user)}

    @app.post("/corax/appeals/{appeal_id}/revoke")
    def revoke_appeal(appeal_id: str, body: RevokeRequest, admin: str = Depends(require_admin)) -> dict:
        record = appeals().revoke(appeal_id, body.exception, admin)
        log.info("appeal %s revoked by %s", appeal_id, admin)
        return record

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

    return app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
app = create_app()
