"""SQLite storage: accounts, documents and access requests (the standard library's sqlite3)."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,   -- the JWT subject and the graph node, e.g. employee_E001
    username   TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('employee', 'admin')),
    role       TEXT,
    department TEXT,
    team       TEXT,
    site       TEXT,
    region     TEXT,
    manager    TEXT,
    password   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_projects (
    user_id TEXT NOT NULL REFERENCES users (id),
    project TEXT NOT NULL,
    PRIMARY KEY (user_id, project)
);
CREATE TABLE IF NOT EXISTS documents (
    id             TEXT PRIMARY KEY,
    title          TEXT NOT NULL,
    department     TEXT NOT NULL,
    classification TEXT NOT NULL,
    site           TEXT,
    region         TEXT,
    content        TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_projects (
    document_id TEXT NOT NULL REFERENCES documents (id),
    project     TEXT NOT NULL,
    PRIMARY KEY (document_id, project)
);
-- status: pending -> rejected | granted (Corax applied the exact exception) | already_granted;
--         granted -> generalised (a rule from the appeal) | exception_only;
--         generalised -> rule_revoked; any granted one -> revoked.
-- Every request waits for an admin: the admin approves, then picks a pattern (confirming a large
-- scope) or keeps only the exception. requested_by: the employee who asked, or the admin who gave
-- access without being asked (a grant: it starts as granted).
CREATE TABLE IF NOT EXISTS access_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL REFERENCES users (id),
    document_id  TEXT NOT NULL REFERENCES documents (id),
    reason       TEXT,
    requested_by TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',
    created_at   TEXT NOT NULL,
    decided_at   TEXT,
    decided_by   TEXT,
    appeal_id    TEXT,
    candidates   TEXT,  -- JSON: the candidate patterns of the appeal
    rule_pattern TEXT,
    tier         TEXT,
    note         TEXT
);
CREATE INDEX IF NOT EXISTS access_requests_user ON access_requests (user_id);
-- An employee who needs documents of a whole unit (a department) without knowing which: the admin
-- sees Corax's ranking of that unit's documents for them and gives some, or rejects.
-- status: pending -> handled (documents: the ids given) | rejected.
CREATE TABLE IF NOT EXISTS unit_requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL REFERENCES users (id),
    unit        TEXT NOT NULL,  -- a department, e.g. finance
    reason      TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    decided_at  TEXT,
    decided_by  TEXT,
    documents   TEXT,  -- JSON: the documents the admin gave
    note        TEXT
);
-- Suggestions from Corax an admin dismissed, so they are not shown again.
CREATE TABLE IF NOT EXISTS dismissed_suggestions (
    user_id      TEXT NOT NULL,
    document_id  TEXT NOT NULL,
    dismissed_by TEXT NOT NULL,
    dismissed_at TEXT NOT NULL,
    PRIMARY KEY (user_id, document_id)
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection



def init(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as connection, connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(SCHEMA)


@contextmanager
def session(path: Path) -> Iterator[sqlite3.Connection]:
    with closing(connect(path)) as connection:
        yield connection


def _projects(connection: sqlite3.Connection, table: str, column: str, key: str) -> list[str]:
    rows = connection.execute(f"SELECT project FROM {table} WHERE {column} = ? ORDER BY project", (key,))
    return [row["project"] for row in rows]


# --- accounts ---------------------------------------------------------------


def user(connection: sqlite3.Connection, user_id: str) -> dict | None:
    row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    found = dict(row)
    found["projects"] = _projects(connection, "user_projects", "user_id", user_id)
    return found


def user_by_login(connection: sqlite3.Connection, login: str) -> dict | None:
    """The account whose username or id is login (case-insensitive)."""
    row = connection.execute(
        "SELECT id FROM users WHERE lower(username) = lower(?) OR lower(id) = lower(?)", (login, login)
    ).fetchone()
    return user(connection, row["id"]) if row else None


def profile(account: dict) -> dict:
    """The account without its password hash."""
    return {key: value for key, value in account.items() if key != "password"}


# --- documents --------------------------------------------------------------


def document(connection: sqlite3.Connection, document_id: str) -> dict | None:
    row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        return None
    found = dict(row)
    found["projects"] = _projects(connection, "document_projects", "document_id", document_id)
    return found


def documents(
    connection: sqlite3.Connection, query: str | None = None, department: str | None = None,
    classification: str | None = None,
) -> list[dict]:  # fmt: skip
    """The catalog: every document without its content, filtered."""
    sql = "SELECT id, title, department, classification, site, region FROM documents WHERE 1 = 1"
    args: list[str] = []
    if query:
        sql += " AND (lower(title) LIKE ? OR lower(id) LIKE ?)"
        args += [f"%{query.lower()}%"] * 2
    if department:
        sql += " AND department = ?"
        args.append(department)
    if classification:
        sql += " AND classification = ?"
        args.append(classification)
    rows = [dict(row) for row in connection.execute(sql + " ORDER BY id", args)]
    projects: dict[str, list[str]] = {}
    for row in connection.execute("SELECT document_id, project FROM document_projects ORDER BY project"):
        projects.setdefault(row["document_id"], []).append(row["project"])
    for row in rows:
        row["projects"] = projects.get(row["id"], [])
    return rows


# --- access requests --------------------------------------------------------

_REQUESTS = """
SELECT r.*, u.name AS user_name, u.role AS user_role, u.department AS user_department,
       u.site AS user_site, u.region AS user_region,
       d.title AS document_title, d.department AS document_department,
       d.site AS document_site, d.region AS document_region,
       d.classification AS document_classification
FROM access_requests r JOIN users u ON u.id = r.user_id JOIN documents d ON d.id = r.document_id
"""


def _request(row: sqlite3.Row) -> dict:
    found = dict(row)
    found["candidates"] = json.loads(found["candidates"]) if found["candidates"] else None
    return found


def access_request(connection: sqlite3.Connection, request_id: int) -> dict | None:
    row = connection.execute(_REQUESTS + " WHERE r.id = ?", (request_id,)).fetchone()
    return _request(row) if row else None


def access_requests(
    connection: sqlite3.Connection, user_id: str | None = None, status: str | None = None
) -> list[dict]:
    sql, args = _REQUESTS + " WHERE 1 = 1", []
    if user_id:
        sql += " AND r.user_id = ?"
        args.append(user_id)
    if status:
        sql += " AND r.status = ?"
        args.append(status)
    return [_request(row) for row in connection.execute(sql + " ORDER BY r.id DESC", args)]


def pending_request(connection: sqlite3.Connection, user_id: str, document_id: str) -> dict | None:
    row = connection.execute(
        _REQUESTS + " WHERE r.user_id = ? AND r.document_id = ? AND r.status = 'pending'",
        (user_id, document_id),
    ).fetchone()
    return _request(row) if row else None


def create_request(
    connection: sqlite3.Connection, user_id: str, document_id: str, reason: str | None, requested_by: str | None = None
) -> int:
    with connection:
        cursor = connection.execute(
            "INSERT INTO access_requests (user_id, document_id, reason, requested_by, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, document_id, reason, requested_by or user_id, now()),
        )
    return cursor.lastrowid


def units(connection: sqlite3.Connection) -> list[str]:
    """The departments that own documents: what an employee may ask for as a whole unit."""
    return [row["department"] for row in connection.execute("SELECT DISTINCT department FROM documents ORDER BY department")]


def create_unit_request(connection: sqlite3.Connection, user_id: str, unit: str, reason: str | None) -> int:
    with connection:
        cursor = connection.execute(
            "INSERT INTO unit_requests (user_id, unit, reason, created_at) VALUES (?, ?, ?, ?)",
            (user_id, unit, reason, now()),
        )
    return cursor.lastrowid


def unit_requests(connection: sqlite3.Connection, user_id: str | None = None, request_id: int | None = None) -> list[dict]:
    sql = """SELECT q.*, u.name AS user_name, u.role AS user_role, u.department AS user_department
             FROM unit_requests q JOIN users u ON u.id = q.user_id WHERE 1 = 1"""
    args: list = []
    if user_id:
        sql += " AND q.user_id = ?"
        args.append(user_id)
    if request_id is not None:
        sql += " AND q.id = ?"
        args.append(request_id)
    found = []
    for row in connection.execute(sql + " ORDER BY q.id DESC", args):
        item = dict(row)
        item["documents"] = json.loads(item["documents"]) if item["documents"] else []
        found.append(item)
    return found


def update_unit_request(connection: sqlite3.Connection, request_id: int, **fields) -> None:
    if "documents" in fields:
        fields["documents"] = json.dumps(fields["documents"])
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connection:
        connection.execute(f"UPDATE unit_requests SET {assignments} WHERE id = ?", (*fields.values(), request_id))


def dismissed(connection: sqlite3.Connection) -> set[tuple[str, str]]:
    return {(row["user_id"], row["document_id"]) for row in connection.execute("SELECT user_id, document_id FROM dismissed_suggestions")}


def dismiss(connection: sqlite3.Connection, user_id: str, document_id: str, by: str) -> None:
    with connection:
        connection.execute(
            "INSERT OR REPLACE INTO dismissed_suggestions VALUES (?, ?, ?, ?)", (user_id, document_id, by, now())
        )


def employees(connection: sqlite3.Connection) -> list[dict]:
    """Every employee, for the admin who gives access (no passwords)."""
    sql = "SELECT id, name, role, department, site, region FROM users WHERE kind = 'employee' ORDER BY id"
    return [dict(row) for row in connection.execute(sql)]


def update_request(connection: sqlite3.Connection, request_id: int, **fields) -> None:
    if fields.get("candidates") is not None:
        fields["candidates"] = json.dumps(fields["candidates"])
    assignments = ", ".join(f"{name} = ?" for name in fields)
    with connection:
        connection.execute(f"UPDATE access_requests SET {assignments} WHERE id = ?", (*fields.values(), request_id))
