"""Fills an empty database from the enterprise graph of scripts/prepare/make_enterprise.py (nodes.csv,
edges.csv): one account per employee, one per Corax admin of demo/data.json, and the documents.
The graph holds no names, titles or texts; they are made up from the node ids, the same every time.
"""

import csv
import hashlib
import sqlite3
from collections import defaultdict
from pathlib import Path

from .security import hash_password

FIRST = ["Ana", "Budi", "Citra", "Dewi", "Eko", "Fajar", "Gita", "Hana", "Indra", "Joko", "Kartika", "Lina",
         "Maya", "Nadia", "Olaf", "Putri", "Rizky", "Sari", "Tono", "Umar", "Vera", "Wulan", "Yusuf", "Zahra",
         "Anna", "Bram", "Clara", "Daan", "Eva", "Finn", "Greta", "Hugo", "Iris", "Jens", "Lotte", "Milan"]  # fmt: skip
# the README scenario: the only Chloe and the only Oscar
NAMED = {"employee_E049": "Chloe Bakker", "employee_E085": "Oscar Weber"}
LAST = ["Wijaya", "Santoso", "Pratama", "Halim", "Kusuma", "Tan", "Lim", "Nugroho", "Setiawan", "Hartono",
        "de Vries", "Jansen", "Bakker", "Visser", "Smit", "Meyer", "Schmidt", "Weber", "Fischer", "Koch"]  # fmt: skip
TOPICS = {
    "sales": ["Quarterly sales plan", "Customer pipeline", "Pricing proposal", "Partner contract",
              "Campaign brief", "Account review"],
    "engineering": ["Architecture notes", "Incident report", "Release plan", "Design review",
                    "Security assessment", "API specification"],
    "finance": ["Budget review", "Audit findings", "Revenue forecast", "Expense policy",
                "Payroll summary", "Tax filing"],
    "operations": ["Supplier list", "Logistics plan", "Facility report", "Inventory audit",
                   "Shift schedule", "Vendor contract"],
    "hr": ["Hiring plan", "Salary bands", "Training catalogue", "Performance review",
           "Onboarding checklist", "Works council minutes"],
    # the other departments of scripts/prepare/make_office.py
    "legal": ["Contract review", "Litigation memo", "Compliance checklist", "NDA template",
              "Regulatory filing", "Board resolution"],
    "marketing": ["Brand guidelines", "Campaign plan", "Market research", "Press release",
                  "Social media calendar", "Product launch brief"],
    "procurement": ["Purchase order log", "Supplier evaluation", "Tender documents", "Framework agreement",
                    "Spend analysis", "Vendor onboarding"],
}  # fmt: skip


def _pick(key: str, choices: list[str], salt: str = "") -> str:
    return choices[hashlib.sha256(f"{salt}{key}".encode()).digest()[0] % len(choices)]


def short(node: str) -> str:
    """'department_sales' -> 'sales', 'role_security_officer' -> 'security_officer'."""
    return node.split("_", 1)[1] if "_" in node else node


def read_graph(seed_dir: Path) -> tuple[dict[str, str], dict[str, dict[str, list[str]]]]:
    with (seed_dir / "nodes.csv").open(newline="", encoding="utf-8") as f:
        types = {row["id"]: row["type"] for row in csv.DictReader(f)}
    facts: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    with (seed_dir / "edges.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["relation"] != "accessed":  # the access history is Corax's business, not the app's
                facts[row["src"]][row["relation"]].append(row["dst"])
    return types, facts


def seed(connection: sqlite3.Connection, seed_dir: Path, admins: frozenset[str], password: str,
         iterations: int) -> dict[str, int] | None:  # fmt: skip
    """Seed an empty database; returns the counts, or None if it holds accounts already."""
    if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return None
    types, facts = read_graph(seed_dir)
    one = lambda node, relation: next(iter(facts[node][relation]), None)  # noqa: E731
    employees = sorted(n for n, t in types.items() if t == "employee")
    documents = sorted(n for n, t in types.items() if t == "document")

    with connection:
        for admin in sorted(admins):
            connection.execute(
                "INSERT INTO users (id, username, name, kind, password) VALUES (?, ?, ?, 'admin', ?)",
                (admin, admin, "Corax admin", hash_password(password, iterations)),
            )
        for employee in employees:
            name = NAMED.get(employee) or f"{_pick(employee, FIRST)} {_pick(employee, LAST, 'last')}"
            connection.execute(
                "INSERT INTO users (id, username, name, kind, role, department, team, site, region,"
                " manager, password) VALUES (?, ?, ?, 'employee', ?, ?, ?, ?, ?, ?, ?)",
                (employee, short(employee).lower(), name, short(one(employee, "holds") or ""),
                 short(one(employee, "works_in") or ""), short(one(employee, "member_of") or ""),
                 short(one(employee, "located_in") or ""), short(one(employee, "based_in") or ""),
                 one(employee, "reports_to"), hash_password(password, iterations)),
            )  # fmt: skip
            connection.executemany(
                "INSERT INTO user_projects (user_id, project) VALUES (?, ?)",
                [(employee, short(p)) for p in facts[employee]["works_on"]],
            )
        for document in documents:
            department = short(one(document, "owned_by") or "")
            projects = [short(p) for p in facts[document]["belongs_to"]]
            level = short(one(document, "classified_as") or "")
            topic = _pick(document, TOPICS.get(department, ["Document"]))
            connection.execute(
                "INSERT INTO documents (id, title, department, classification, site, region, content)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (document, f"{topic} ({short(document)})", department, level,
                 short(one(document, "stored_at") or ""), short(one(document, "stored_in") or ""),
                 _content(document, topic, department, projects, level)),
            )  # fmt: skip
            connection.executemany(
                "INSERT INTO document_projects (document_id, project) VALUES (?, ?)",
                [(document, p) for p in projects],
            )
    return {"admins": len(admins), "employees": len(employees), "documents": len(documents)}


def _content(document: str, topic: str, department: str, projects: list[str], level: str) -> str:
    revision = hashlib.sha256(document.encode()).digest()[1] % 9 + 1
    return (
        f"{topic}, revision {revision}.\n\n"
        f"Owned by the {department} department for the projects {' and '.join(projects)}. "
        f"Classification: {level}.\n\n"
        "This text stands in for the real content: what matters in the demo is who may read it."
    )
