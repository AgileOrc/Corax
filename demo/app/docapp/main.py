"""The document app: a small document-management API that Corax protects (deploy/README.md).

Corax decides who may do what: every route except /auth/login and /health reaches the app only
when OPA allowed it at the gateway (the routes and actions are in demo/data.json, the
rules in demo/policy and the rules from appeals). The app has no authorization of its
own, on purpose: without the gateway anyone could read any document by changing the id (BOLA).
It still checks who is calling (the JWT), to know whose requests to show, and that an admin
endpoint is called by an admin.

An employee who is denied a document asks for access here, and the request waits for an admin. The
admin's approval starts the appeal in Corax with the admin's own token (the exact exception at once,
then candidate patterns); the admin then picks a pattern (confirming a large one) or keeps only the
exception. The app never calls Corax on its own: it has no Corax admin account, so only a person
decides who gets access.

    uvicorn --factory docapp.main:create_app
"""

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import db, seed
from .corax import Corax
from .opa import Opa, OpaError
from .security import TokenError, Tokens, verify_password
from .settings import Settings

log = logging.getLogger("uvicorn.error")  # shown in the container log next to uvicorn's own lines


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class AccessRequestBody(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)


class Confirm(BaseModel):
    candidate: int | None = None  # None: keep only the exception
    acknowledge_scope: bool = False


class Reject(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


# the request statuses after which the employee may open the document
OPENED = {"granted", "generalised", "exception_only", "rule_revoked", "already_granted"}


class Revoke(BaseModel):
    exception: bool = False


class UnitRequest(BaseModel):
    unit: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=1000)


class UnitGrant(BaseModel):
    documents: list[str] = Field(min_length=1, max_length=50)


class Dismiss(BaseModel):
    user: str = Field(min_length=1, max_length=256)
    document: str = Field(min_length=1, max_length=256)


class Grant(BaseModel):
    user: str = Field(min_length=1, max_length=256)
    document: str = Field(min_length=1, max_length=256)
    reason: str | None = Field(default=None, max_length=1000)  # also take back the employee's own exception, not only the rule


def create_app(settings: Settings | None = None, corax: Corax | None = None, opa: Opa | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    tokens = Tokens(settings.corax_config, settings.token_minutes)
    corax = corax or Corax(settings.corax_gateway)
    opa = opa or Opa(settings.opa_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db.init(settings.database)
        if settings.seed_dir:
            with db.session(settings.database) as connection:
                counts = seed.seed(connection, settings.seed_dir, tokens.admins, settings.demo_password,
                                   settings.password_iterations)  # fmt: skip
            if counts:
                log.info("seeded %s from %s", counts, settings.seed_dir)
        yield

    app = FastAPI(title="Corax demo document app", lifespan=lifespan)

    def connection() -> Iterator[sqlite3.Connection]:
        with db.session(settings.database) as opened:
            yield opened

    Connection = Annotated[sqlite3.Connection, Depends(connection)]

    def bearer(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
        return authorization.removeprefix("Bearer ")

    Token = Annotated[str, Depends(bearer)]

    def current_user(token: Token, c: Connection) -> dict:
        try:
            subject = tokens.subject(token)
        except TokenError as error:
            raise HTTPException(401, f"invalid token: {error}", headers={"WWW-Authenticate": "Bearer"}) from error
        account = db.user(c, subject)
        if account is None:
            raise HTTPException(401, f"unknown user {subject!r}")
        return account

    Account = Annotated[dict, Depends(current_user)]

    def admin_user(account: Account) -> dict:
        if account["kind"] != "admin":
            raise HTTPException(403, "admins only")
        return account

    Admin = Annotated[dict, Depends(admin_user)]

    def request_in(c: sqlite3.Connection, request_id: int, status: str) -> dict:
        request = db.access_request(c, request_id)
        if request is None:
            raise HTTPException(404, f"unknown access request {request_id}")
        if request["status"] != status:
            raise HTTPException(409, f"access request {request_id} is {request['status']}, not {status}")
        return request

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    # --- sign in (the only route Envoy lets through without a token) -------

    @app.post("/auth/login")
    def login(body: Login, c: Connection) -> dict:
        account = db.user_by_login(c, body.username.strip())
        if account is None or not verify_password(body.password, account["password"]):
            raise HTTPException(401, "wrong username or password")
        token, seconds = tokens.issue(account["id"])
        return {"token": token, "token_type": "Bearer", "expires_in": seconds, "user": db.profile(account)}

    @app.get("/me")
    def me(account: Account) -> dict:
        return db.profile(account)

    # --- documents --------------------------------------------------------

    @app.get("/documents")
    def catalog(
        account: Account, c: Connection, q: Annotated[str | None, Query(max_length=100)] = None,
        department: str | None = None, classification: str | None = None,
    ) -> dict:  # fmt: skip
        """Titles and metadata of the documents the policy lets this employee open, nothing else: the
        titles of the rest are not shown, so nobody learns what exists from the catalog. Admins see
        every document, to grant access. Opening one is still checked by Corax at the gateway, with
        the AI check. in_my_projects is a hint for the user interface, not a permission."""
        found = db.documents(c, q, department, classification)
        if account["kind"] != "admin":
            try:
                allowed = opa.allowed_objects(account["id"], "read", "document", [d["id"] for d in found])
            except OpaError as error:  # fail closed: list nothing rather than everything
                raise HTTPException(503, f"cannot check which documents you may open: {error}") from error
            found = [d for d in found if d["id"] in allowed]
        mine = set(account["projects"])
        for document in found:
            document["in_my_projects"] = bool(mine & set(document["projects"]))
        return {"documents": found, "count": len(found)}

    @app.get("/documents/{document_id}")
    def read(document_id: str, _: Account, c: Connection) -> dict:
        document = db.document(c, document_id)
        if document is None:
            raise HTTPException(404, f"unknown document {document_id!r}")
        return document

    @app.get("/documents/{document_id}/summary")
    def summary(document_id: str, _: Account, c: Connection) -> dict:
        """The first paragraph only. Its route is deliberately too broad (every employee), so the
        AI check is what stops the unusual pairs."""
        document = db.document(c, document_id)
        if document is None:
            raise HTTPException(404, f"unknown document {document_id!r}")
        keep = ("id", "title", "department", "classification", "site", "region", "projects")
        return {**{key: document[key] for key in keep}, "summary": document["content"].split("\n\n")[0]}

    # --- access requests (employees) ---------------------------------------

    @app.post("/access-requests/{document_id}", status_code=201)
    def request_access(document_id: str, account: Account, c: Connection, body: AccessRequestBody | None = None) -> dict:
        if account["kind"] != "employee":
            raise HTTPException(403, "only employees ask for access")
        if open_request := db.pending_request(c, account["id"], document_id):
            raise HTTPException(409, f"access request {open_request['id']} for {document_id} is still pending")
        if db.document(c, document_id) is None:
            # the same answer as for a document that exists, so asking does not tell which ids exist;
            # nothing is stored, and no admin sees it
            return {"id": None, "status": "pending", "document_id": document_id}
        reason = body.reason if body else None
        request_id = db.create_request(c, account["id"], document_id, reason)
        return hidden(db.access_request(c, request_id))

    @app.get("/access-requests")
    def my_requests(account: Account, c: Connection) -> dict:
        return {"requests": [hidden(r) for r in db.access_requests(c, user_id=account["id"])]}

    def hidden(request: dict) -> dict:
        """An employee's own request without the document's title and details until access is granted:
        asking for a document by its link must not reveal what it is."""
        if request["status"] in OPENED:
            return request
        return {k: v for k, v in request.items() if not k.startswith("document_") or k == "document_id"}

    # --- access requests (admins) ------------------------------------------

    @app.get("/admin/access-requests")
    def all_requests(_: Admin, c: Connection, status: str | None = None) -> dict:
        return {"requests": db.access_requests(c, status=status)}

    @app.get("/admin/employees")
    def all_employees(_: Admin, c: Connection) -> dict:
        return {"employees": db.employees(c)}

    @app.get("/admin/employees/{user_id}/documents")
    def documents_to_give(user_id: str, _: Admin, c: Connection) -> dict:
        """The documents this employee cannot open yet, the only ones worth giving: the policy (OPA's
        allowed_objects, as for the catalog) already lets them open the rest."""
        employee = db.user(c, user_id)
        if employee is None or employee["kind"] != "employee":
            raise HTTPException(404, f"unknown employee {user_id!r}")
        found = db.documents(c)
        try:
            allowed = opa.allowed_objects(user_id, "read", "document", [d["id"] for d in found])
        except OpaError as error:
            raise HTTPException(503, f"cannot check which documents this employee may open: {error}") from error
        return {"documents": [d for d in found if d["id"] not in allowed]}

    def give(c: sqlite3.Connection, admin: dict, token: str, user: str, document: str, reason: str | None) -> tuple[dict, dict]:
        """A request that starts approved: Corax writes the exact exception and proposes rules for
        people in the same situation; the admin then picks one or keeps only the exception."""
        employee = db.user(c, user)
        if employee is None or employee["kind"] != "employee":
            raise HTTPException(404, f"unknown employee {user!r}")
        if db.document(c, document) is None:
            raise HTTPException(404, f"unknown document {document!r}")
        request_id = db.create_request(c, user, document, reason, requested_by=admin["id"])
        status, appeal = corax.create_appeal(token, user, document, reason)
        decided = {"decided_at": db.now(), "decided_by": admin["id"]}
        if status == 201:
            db.update_request(c, request_id, status="granted", appeal_id=appeal["id"],
                              candidates=appeal.get("candidates"), **decided)  # fmt: skip
        elif status == 409:  # the service: the employee can read the document already
            db.update_request(c, request_id, status="already_granted", note=appeal.get("error"), **decided)
        else:
            with c:
                c.execute("DELETE FROM access_requests WHERE id = ?", (request_id,))
            raise HTTPException(502, {"message": "Corax did not accept the grant", "status": status, "corax": appeal})
        return db.access_request(c, request_id), appeal

    @app.post("/admin/grants", status_code=201)
    def grant(body: Grant, admin: Admin, token: Token, c: Connection) -> dict:
        """The admin gives an employee a document without being asked (see give)."""
        request, appeal = give(c, admin, token, body.user, body.document, body.reason)
        return {"request": request, "appeal": appeal}

    # --- suggested access (A) ----------------------------------------------

    @app.get("/admin/suggestions")
    def suggestions(_: Admin, token: Token, c: Connection) -> dict:
        """Access Corax's model expects but nobody granted yet, with the people and documents named;
        the ones an admin dismissed are left out. Nothing is granted until an admin gives it."""
        status, answer = corax.suggestions(token, 100)
        if status != 200:
            raise HTTPException(502, {"message": "Corax did not answer", "status": status, "corax": answer})
        hidden = db.dismissed(c)
        found = []
        for s in answer.get("items", []):
            if (s["user"], s["object"]) in hidden:
                continue
            employee, document = db.user(c, s["user"]), db.document(c, s["object"])
            if employee is None or document is None:
                continue
            found.append({**s, "user_name": employee["name"], "user_role": employee["role"],
                          "user_department": employee["department"], "user_site": employee["site"],
                          "user_region": employee["region"], "document_title": document["title"],
                          "document_department": document["department"], "document_site": document["site"],
                          "document_region": document["region"],
                          "document_classification": document["classification"]})  # fmt: skip
        return {"suggestions": found}

    @app.post("/admin/suggestions/dismiss")
    def dismiss_suggestion(body: Dismiss, admin: Admin, c: Connection) -> dict:
        db.dismiss(c, body.user, body.document, admin["id"])
        return {"dismissed": True}

    # --- requests for a whole unit (C) -------------------------------------

    @app.get("/units")
    def units(account: Account, c: Connection) -> dict:
        """The departments an employee may ask for, their own first. Only department names, which
        every employee knows; never document titles."""
        found = db.units(c)
        own = account.get("department")
        return {"units": sorted(found, key=lambda unit: (unit != own, unit))}

    @app.post("/unit-requests", status_code=201)
    def request_unit(body: UnitRequest, account: Account, c: Connection) -> dict:
        if account["kind"] != "employee":
            raise HTTPException(403, "only employees ask for access")
        if body.unit not in db.units(c):
            raise HTTPException(422, f"unknown unit {body.unit!r}")
        request_id = db.create_unit_request(c, account["id"], body.unit, body.reason)
        return unit_view(db.unit_requests(c, request_id=request_id)[0])

    @app.get("/unit-requests")
    def my_unit_requests(account: Account, c: Connection) -> dict:
        return {"requests": [unit_view(r) for r in db.unit_requests(c, user_id=account["id"])]}

    def unit_view(request: dict) -> dict:
        """An employee's own unit request: how many documents were given, never which ones are in the unit."""
        return {k: v for k, v in request.items() if k != "documents"} | {"given": len(request["documents"])}

    @app.get("/admin/unit-requests")
    def all_unit_requests(_: Admin, c: Connection) -> dict:
        return {"requests": db.unit_requests(c)}

    def unit_request(c: sqlite3.Connection, request_id: int, status: str | None = None) -> dict:
        found = db.unit_requests(c, request_id=request_id)
        if not found:
            raise HTTPException(404, f"unknown unit request {request_id}")
        if status and found[0]["status"] != status:
            raise HTTPException(409, f"unit request {request_id} is {found[0]['status']}, not {status}")
        return found[0]

    @app.get("/admin/unit-requests/{request_id}/documents")
    def unit_documents(request_id: int, _: Admin, token: Token, c: Connection) -> dict:
        """The unit's documents the employee cannot open yet, ranked by Corax for them: how many of the
        people most like them can open each, and a warning when none can open anything there."""
        request = unit_request(c, request_id)
        status, ranked = corax.rank(token, request["user_id"], "owned_by", f"department_{request['unit']}")
        if status != 200:
            raise HTTPException(502, {"message": "Corax did not answer", "status": status, "corax": ranked})
        documents = []
        for item in ranked.get("objects", []):
            document = db.document(c, item["object"])
            if document is not None:
                documents.append({**item, "title": document["title"], "classification": document["classification"]})
        return {"request": request, "documents": documents, "warning": ranked.get("warning")}

    @app.post("/admin/unit-requests/{request_id}/grant")
    def grant_unit(request_id: int, body: UnitGrant, admin: Admin, token: Token, c: Connection) -> dict:
        """Give the documents the admin ticked: each one is a grant (see give), so Corax proposes rules
        for people in the same situation for each."""
        request = unit_request(c, request_id, "pending")
        reason = f"unit request #{request_id}" + (f": {request['reason']}" if request["reason"] else "")
        given = [give(c, admin, token, request["user_id"], document, reason)[0] for document in body.documents]
        db.update_unit_request(c, request_id, status="handled", decided_at=db.now(), decided_by=admin["id"],
                               documents=body.documents)  # fmt: skip
        return {"request": unit_request(c, request_id), "granted": given}

    @app.post("/admin/unit-requests/{request_id}/reject")
    def reject_unit(request_id: int, admin: Admin, c: Connection, body: Reject | None = None) -> dict:
        unit_request(c, request_id, "pending")
        db.update_unit_request(c, request_id, status="rejected", decided_at=db.now(), decided_by=admin["id"],
                               note=body.note if body else None)  # fmt: skip
        return {"request": unit_request(c, request_id)}

    @app.post("/admin/access-requests/{request_id}/approve")
    def approve(request_id: int, admin: Admin, token: Token, c: Connection) -> dict:
        """Start the appeal in Corax with the admin's token: the exact exception applies at once, and
        the request waits for the admin's choice of a pattern (see confirm)."""
        request = request_in(c, request_id, "pending")
        status, appeal = corax.create_appeal(token, request["user_id"], request["document_id"], request["reason"])
        decided = {"decided_at": db.now(), "decided_by": admin["id"]}
        if status == 201:
            db.update_request(c, request_id, status="granted", appeal_id=appeal["id"],
                              candidates=appeal.get("candidates"), **decided)  # fmt: skip
        elif status == 409:  # the service: the user can read the document already
            db.update_request(c, request_id, status="already_granted", note=appeal.get("error"), **decided)
        else:
            raise HTTPException(502, {"message": "Corax did not accept the appeal", "status": status, "corax": appeal})
        return {"request": db.access_request(c, request_id), "appeal": appeal}

    @app.post("/admin/access-requests/{request_id}/confirm")
    def confirm(request_id: int, body: Confirm, _: Admin, token: Token, c: Connection) -> JSONResponse:
        """Generalise a granted request with a candidate pattern, or keep only its exception
        (candidate null). A large pattern answers 409 with its scope until acknowledge_scope."""
        request = request_in(c, request_id, "granted")
        status, appeal = corax.confirm(token, request["appeal_id"], body.candidate, body.acknowledge_scope)
        if status == 200 and appeal.get("status") == "rule_applied":
            chosen = appeal["chosen"]
            db.update_request(c, request_id, status="generalised", rule_pattern=chosen["pattern"],
                              tier=chosen["scope"]["tier"])  # fmt: skip
        elif status == 200 and appeal.get("status") == "exception_only":
            db.update_request(c, request_id, status="exception_only")
        elif status not in (409, 422):  # 409: large scope to acknowledge, 422: the rule failed validation
            raise HTTPException(502, {"message": "Corax did not accept the choice", "status": status, "corax": appeal})
        return JSONResponse(status_code=status, content={"request": db.access_request(c, request_id), "appeal": appeal})

    @app.post("/admin/access-requests/{request_id}/revoke")
    def revoke(request_id: int, admin: Admin, token: Token, c: Connection, body: Revoke | None = None) -> JSONResponse:
        """Take back what a granted request opened, through Corax so the revoke is recorded: the rule
        (rule_revoked, the employee keeps the exact exception), or with exception the exception too
        (revoked). 409 from Corax when nothing of the appeal is still in effect."""
        request = db.access_request(c, request_id)
        if request is None:
            raise HTTPException(404, f"unknown access request {request_id}")
        if not request["appeal_id"] or request["status"] not in ("granted", "generalised", "exception_only", "rule_revoked"):
            raise HTTPException(409, f"access request {request_id} is {request['status']}: nothing to revoke")
        exception = bool(body and body.exception)
        status, appeal = corax.revoke(token, request["appeal_id"], exception)
        if status == 200:
            db.update_request(c, request_id, status="revoked" if exception else "rule_revoked",
                              note=f"Revoked by {admin['id']} on {db.now()}")  # fmt: skip
        elif status != 409:
            raise HTTPException(502, {"message": "Corax did not revoke", "status": status, "corax": appeal})
        return JSONResponse(status_code=status, content={"request": db.access_request(c, request_id), "appeal": appeal})

    @app.post("/admin/access-requests/{request_id}/reject")
    def reject(request_id: int, admin: Admin, c: Connection, body: Reject | None = None) -> dict:
        request_in(c, request_id, "pending")
        db.update_request(c, request_id, status="rejected", decided_at=db.now(), decided_by=admin["id"],
                          note=body.note if body else None)  # fmt: skip
        return {"request": db.access_request(c, request_id)}

    return app
