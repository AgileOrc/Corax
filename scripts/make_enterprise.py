"""Write a synthetic enterprise graph (nodes.csv, edges.csv) with two hidden policies, its appeal
scenarios (scenarios.json, see appeal_scenarios.py) and the named requests of the demo (demo.json).

    employee -member_of-> team -part_of-> department     employee -works_in-> department
    employee -holds-> role                                employee -reports_to-> employee
    employee -located_in-> site -in_region-> region       employee -based_in-> region
    employee -works_on-> project -owned_by-> department   (one or two, sometimes another department)
    document -belongs_to-> project    document -owned_by-> department
    document -stored_at-> site        document -stored_in-> region
    document -classified_as-> classification
    employee -accessed-> document     (target relation: the access history)

The current policy, recorded as "accessed" edges: an employee reads the documents of the projects
they work on, and the public documents of their own department. Department and region are also
direct edges, so the pattern miner's one-hop predicates can express the hidden policies:

  manager           a manager reads every document of their department
                    (user.works_in = object.owned_by AND user holds role_manager)
  security_officer  a security officer reads every document stored in their region
                    (user.based_in = object.stored_in AND user holds role_security_officer)
  one_off           an engineer asks for a confidential document of another project; nothing should
                    generalise: any pattern would open most of their department

Example:
    python scripts/make_enterprise.py output/enterprise-data
    python hgnn-job/run.py --data output/enterprise-data --target-relation accessed \
        --out output/enterprise
    python scripts/evaluate_appeals.py --model-dir output/enterprise \
        --scenarios output/enterprise-data/scenarios.json
"""

import argparse
import csv
import json
import random
from pathlib import Path

import appeal_scenarios

DEPARTMENTS = ["sales", "engineering", "finance", "operations"]
REGIONS = {"emea": ["frankfurt", "amsterdam"], "apac": ["singapore", "jakarta"]}
CLASSIFICATIONS = [("public", 0.3), ("internal", 0.5), ("confidential", 0.2)]
ROLES = ["engineer", "analyst", "manager", "security_officer", "auditor"]
# the demo's admin: a JWT subject, not a node of the graph
ADMIN = "admin_01"


def build(teams: int, team_size: int, projects: int, documents: int, seed: int):
    """Return nodes, edges, the appeal scenarios and the demo requests."""
    rng = random.Random(seed)
    nodes: list[tuple[str, str]] = []
    edges: list[tuple[str, str, str]] = []
    site_region = {site: region for region, sites in REGIONS.items() for site in sites}
    sites = sorted(site_region)

    nodes += [(f"role_{role}", "role") for role in ROLES]
    nodes += [(f"classification_{level}", "classification") for level, _ in CLASSIFICATIONS]
    nodes += [(f"region_{region}", "region") for region in REGIONS]
    for site in sites:
        nodes.append((f"site_{site}", "site"))
        edges.append((f"site_{site}", "in_region", f"region_{site_region[site]}"))

    owned: dict[str, list[str]] = {}
    for department in DEPARTMENTS:
        nodes.append((f"department_{department}", "department"))
        for t in range(teams):
            nodes.append((f"team_{department}{t + 1}", "team"))
            edges.append((f"team_{department}{t + 1}", "part_of", f"department_{department}"))
        owned[department] = [f"project_{department}{p + 1}" for p in range(projects)]
        for project in owned[department]:
            nodes.append((project, "project"))
            edges.append((project, "owned_by", f"department_{department}"))

    # one manager per department, two security officers (one per region), two auditors in
    # finance; everyone else is an engineer (engineering) or an analyst
    employees: dict[str, dict] = {}
    for department in DEPARTMENTS:
        manager = None
        for t in range(teams):
            for i in range(team_size):
                employee = f"employee_E{len(employees) + 1:03d}"
                role = "engineer" if department == "engineering" else "analyst"
                site = rng.choice(sites)
                if t == 0 and i == 0:
                    role = "manager"
                elif (department, t, i) == ("operations", 0, 1):
                    role, site = "security_officer", "frankfurt"
                elif (department, t, i) == ("finance", 1, 1):
                    role, site = "security_officer", "singapore"
                elif department == "finance" and t == 0 and i in (2, 3):
                    role = "auditor"
                worked = rng.sample(owned[department], k=rng.choice([1, 1, 2]))
                if rng.random() < 0.2:
                    other = rng.choice([d for d in DEPARTMENTS if d != department])
                    worked.append(rng.choice(owned[other]))
                employees[employee] = {
                    "department": department, "role": role, "site": site, "projects": worked,
                }  # fmt: skip
                manager = employee if role == "manager" else manager
                nodes.append((employee, "employee"))
                edges += [
                    (employee, "member_of", f"team_{department}{t + 1}"),
                    (employee, "works_in", f"department_{department}"),
                    (employee, "holds", f"role_{role}"),
                    (employee, "located_in", f"site_{site}"),
                    (employee, "based_in", f"region_{site_region[site]}"),
                ]
                edges += [(employee, "works_on", project) for project in worked]
                if role != "manager":
                    edges.append((employee, "reports_to", manager))

    docs: dict[str, dict] = {}
    levels, weights = zip(*CLASSIFICATIONS, strict=True)
    for department in DEPARTMENTS:
        for project in owned[department]:
            for _ in range(documents):
                document = f"document_D{len(docs) + 1:03d}"
                site = rng.choice(sites)
                level = rng.choices(levels, weights)[0]
                docs[document] = {
                    "department": department, "project": project, "site": site, "level": level,
                }  # fmt: skip
                nodes.append((document, "document"))
                edges += [
                    (document, "belongs_to", project),
                    (document, "owned_by", f"department_{department}"),
                    (document, "stored_at", f"site_{site}"),
                    (document, "stored_in", f"region_{site_region[site]}"),
                    (document, "classified_as", f"classification_{level}"),
                ]

    def allowed(e: dict, d: dict) -> bool:
        return d["project"] in e["projects"] or (
            d["level"] == "public" and d["department"] == e["department"]
        )

    permitted = {(e, d) for e in employees for d in docs if allowed(employees[e], docs[d])}
    edges += [(e, "accessed", d) for e, d in sorted(permitted)]

    scenarios, demo = _appeals(employees, docs, permitted, site_region)
    return nodes, edges, scenarios, demo


def _appeals(employees: dict, docs: dict, permitted: set, site_region: dict):
    def region(site: str) -> str:
        return site_region[site]

    def with_role(role: str, department: str | None = None) -> list[str]:
        return [
            e
            for e, a in employees.items()
            if a["role"] == role and department in (None, a["department"])
        ]

    def denied(employee: str, *tests) -> str:
        """The first document the employee may not read now that passes a test; the later tests
        are looser, for graphs where no document passes the first."""
        for test in tests:
            found = [d for d, a in docs.items() if (employee, d) not in permitted and test(a)]
            if found:
                return found[0]
        raise ValueError(f"no document denied to {employee}; generate a larger graph")

    def not_yet(pairs) -> list[tuple[str, str]]:
        return [pair for pair in pairs if pair not in permitted]

    managers, officers = with_role("manager"), with_role("security_officer")
    manager_pairs = not_yet(
        (e, d) for e in managers for d, a in docs.items()
        if a["department"] == employees[e]["department"]
    )  # fmt: skip
    officer_pairs = not_yet(
        (e, d) for e in officers for d, a in docs.items()
        if region(a["site"]) == region(employees[e]["site"])
    )  # fmt: skip

    # only the department links the sales manager to this document (it is in another region)
    sales_manager = with_role("manager", "sales")[0]
    m = employees[sales_manager]
    manager_doc = denied(
        sales_manager,
        lambda d: d["department"] == "sales" and region(d["site"]) != region(m["site"]),
        lambda d: d["department"] == "sales",
    )
    # only the region links the EMEA officer to this document (other department, other site)
    officer_emea, officer_apac = (
        next(e for e in officers if region(employees[e]["site"]) == r) for r in ("emea", "apac")
    )
    o = employees[officer_emea]
    officer_doc = denied(
        officer_emea,
        lambda d: region(d["site"]) == "emea" and d["department"] != o["department"]
        and d["site"] != o["site"],
        lambda d: region(d["site"]) == "emea" and d["department"] != o["department"],
        lambda d: region(d["site"]) == "emea",
    )  # fmt: skip
    engineer = with_role("engineer")[1]
    engineer_doc = denied(
        engineer,
        lambda d: d["department"] == "engineering" and d["level"] == "confidential",
        lambda d: d["level"] == "confidential",
    )

    scenarios = [
        {
            "name": "manager",
            "appeal": (sales_manager, manager_doc),
            "expected": [
                {"kind": "shared", "relation": "works_in", "other": "owned_by"},
                {"kind": "user_has", "relation": "holds", "other": "role_manager"},
            ],
            "hidden_pairs": manager_pairs,
        },
        {
            "name": "security_officer",
            "appeal": (officer_emea, officer_doc),
            "expected": [
                {"kind": "shared", "relation": "based_in", "other": "stored_in"},
                {"kind": "user_has", "relation": "holds", "other": "role_security_officer"},
            ],
            "hidden_pairs": officer_pairs,
        },
        {"name": "one_off", "appeal": (engineer, engineer_doc), "expected": None, "hidden_pairs": []},
    ]

    member_doc = next(d for d in docs if (engineer, d) in permitted
                      and docs[d]["project"] in employees[engineer]["projects"])  # fmt: skip
    engineering_manager = with_role("manager", "engineering")[0]
    a = employees[officer_apac]
    apac_doc = denied(
        officer_apac,
        lambda d: region(d["site"]) == "apac" and d["department"] != a["department"],
        lambda d: region(d["site"]) == "apac",
    )
    sales_analyst = with_role("analyst", "sales")[0]
    finance_doc = denied(
        sales_analyst,
        lambda d: d["department"] == "finance" and d["level"] == "confidential",
        lambda d: d["department"] == "finance",
    )
    reads = [
        ("Project member reads a document of their project", engineer, member_doc),
        ("Sales manager reads a Sales document outside their projects", sales_manager, manager_doc),
        ("Engineering manager reads an Engineering document", engineering_manager,
         denied(engineering_manager, lambda d: d["department"] == "engineering")),
        ("Security officer (EMEA) reads a document stored in EMEA", officer_emea, officer_doc),
        ("Security officer (APAC) reads a document stored in APAC", officer_apac, apac_doc),
        ("Engineer reads a confidential document of another project", engineer, engineer_doc),
        ("Sales analyst reads a confidential Finance document (BOLA)", sales_analyst, finance_doc),
    ]  # fmt: skip
    appeals = [
        ("Sales manager asks for a Sales document", "manager",
         "generalizes: managers read the documents of their own department"),
        ("Security officer (EMEA) asks for a document stored in EMEA", "security_officer",
         "generalizes: security officers read the documents stored in their region"),
        ("Engineer asks for a confidential document of another project", "one_off",
         "must not generalize: only the exact exception"),
    ]  # fmt: skip
    appeal_of = {s["name"]: s["appeal"] for s in scenarios}
    demo = {
        "admin": ADMIN,
        "reads": [{"name": n, "user": u, "document": d} for n, u, d in reads],
        "appeals": [
            {"name": n, "scenario": s, "user": appeal_of[s][0], "document": appeal_of[s][1],
             "expect": x}
            for n, s, x in appeals
        ],  # fmt: skip
    }
    return scenarios, demo


def write(out_dir: Path, nodes, edges, scenarios, demo) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "nodes.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("id", "type"), *nodes])
    with (out_dir / "edges.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("src", "relation", "dst"), *edges])
    appeal_scenarios.write(out_dir, "accessed", False, scenarios)
    (out_dir / "demo.json").write_text(json.dumps(demo, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a synthetic enterprise graph.")
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--teams", type=int, default=2, help="per department")
    parser.add_argument("--team-size", type=int, default=12)
    parser.add_argument("--projects", type=int, default=3, help="per department")
    parser.add_argument("--documents", type=int, default=8, help="per project")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if args.teams < 2 or args.team_size < 4:
        parser.error("needs at least 2 teams of 4 per department")
    nodes, edges, scenarios, demo = build(
        args.teams, args.team_size, args.projects, args.documents, args.seed
    )
    write(args.out_dir, nodes, edges, scenarios, demo)
    accessed = sum(e[1] == "accessed" for e in edges)
    print(f"{len(nodes)} nodes, {len(edges)} edges ({accessed} accessed) in {args.out_dir}")
    print(f"{len(scenarios)} appeal scenarios in {args.out_dir / 'scenarios.json'}")


if __name__ == "__main__":
    main()
