"""Write a synthetic enterprise graph (nodes.csv, edges.csv) with nine hidden policies, its appeal
scenarios (scenarios.json, see appeal_scenarios.py) and the named requests, appeals and summary
readers of the demo (demo.json).

    employee -member_of-> team -part_of-> department     employee -works_in-> department
    employee -holds-> role                                employee -reports_to-> employee
    employee -located_in-> site -in_region-> region       employee -based_in-> region
    employee -works_on-> project -owned_by-> department   (two of their department's, sometimes
                                                           one more of another department)
    employee -cleared_for-> classification                (the auditors: confidential)
    employee -supports-> department                       (the HR partners: one department each)
    document -belongs_to-> project    (two projects of its department)
    document -owned_by-> department
    document -stored_at-> site        document -stored_in-> region
    document -classified_as-> classification
    employee -accessed-> document     (target relation: the access history)

The current policy, recorded as "accessed" edges: an employee reads the documents of the projects
they work on, and the public documents of their own department. Like courses on a campus, an
employee and a document each have two of the department's four projects, so most employees already
read most documents of their department and a department-wide rule opens only the few documents
that share no project with them. Department, region, site, clearance and supported department are
direct edges, so the pattern miner's one-hop predicates can express the hidden policies:

  manager, coordinator,     one holder per department, who reads every document of their department
  data_steward,             (user.works_in = object.owned_by AND user holds role_<role>): small rules,
  quality_lead              5 users and a few pairs each
  security_officer          reads every document stored in their region (based_in = stored_in)
  facility_manager          reads every document stored at their site (located_in = stored_at)
  auditor                   reads every confidential document (cleared_for = classified_as)
  hr_partner                reads every document of the department they support (supports = owned_by)
  one_off, one_off_hr       a single exception; nothing should generalise

The last five open many pairs of other departments: large rules, for the admin to decide.

The demo builds the graph and trains the HGNN in one step (python scripts/demo_gateway.py prepare).
By hand:
    python scripts/prepare/make_enterprise.py output/enterprise-data
    python -m hgnn --data output/enterprise-data --target-relation accessed \
        --out output/enterprise --learning-rate 0.01 --patience 50
"""

import argparse
import csv
import json
import random
from pathlib import Path

import appeal_scenarios

DEPARTMENTS = ["sales", "engineering", "finance", "operations", "hr"]
REGIONS = {"emea": ["frankfurt", "amsterdam"], "apac": ["singapore", "jakarta"]}
CLASSIFICATIONS = [("public", 0.3), ("internal", 0.5), ("confidential", 0.2)]
# (team, index in the team) -> a role held once per department, with a department-wide hidden policy
DEPARTMENT_ROLES = {(0, 0): "manager", (1, 0): "coordinator", (2, 0): "data_steward", (0, 1): "quality_lead"}
# (department, team, index) -> a company-wide role and its fixed site (None: drawn like everyone's)
SPECIAL = {
    ("operations", 0, 2): ("security_officer", "frankfurt"),
    ("finance", 1, 2): ("security_officer", "singapore"),
    ("finance", 0, 3): ("auditor", None),
    ("finance", 0, 4): ("auditor", None),
    ("operations", 1, 1): ("facility_manager", "frankfurt"),
    ("operations", 1, 2): ("facility_manager", "amsterdam"),
    ("operations", 1, 3): ("facility_manager", "singapore"),
    ("operations", 1, 4): ("facility_manager", "jakarta"),
    ("hr", 2, 1): ("hr_partner", None),
    ("hr", 2, 2): ("hr_partner", None),
    ("hr", 2, 3): ("hr_partner", None),
    ("hr", 2, 4): ("hr_partner", None),
}
SUPPORTS = {("hr", 2, 1): "sales", ("hr", 2, 2): "engineering", ("hr", 2, 3): "finance", ("hr", 2, 4): "operations"}
ROLES = ["engineer", "analyst", *DEPARTMENT_ROLES.values(), "security_officer", "auditor", "facility_manager",
         "hr_partner"]  # fmt: skip
# the demo's admin: a JWT subject, not a node of the graph
ADMIN = "admin_01"
MIN_TEAMS, MIN_TEAM_SIZE = 3, 5  # the roles above sit in the first three teams, at index 0 to 4


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

    # the roles of DEPARTMENT_ROLES and SPECIAL; everyone else is an engineer (engineering) or an analyst
    employees: dict[str, dict] = {}
    for department in DEPARTMENTS:
        manager = None
        for t in range(teams):
            for i in range(team_size):
                employee = f"employee_E{len(employees) + 1:03d}"
                role = "engineer" if department == "engineering" else "analyst"
                site = rng.choice(sites)
                role = DEPARTMENT_ROLES.get((t, i), role)
                if (department, t, i) in SPECIAL:
                    role, fixed = SPECIAL[department, t, i]
                    site = fixed or site
                worked = rng.sample(owned[department], k=2)
                if rng.random() < 0.2:
                    other = rng.choice([d for d in DEPARTMENTS if d != department])
                    worked.append(rng.choice(owned[other]))
                employees[employee] = {
                    "department": department, "role": role, "site": site, "region": site_region[site],
                    "projects": worked, "supports": SUPPORTS.get((department, t, i)),
                    "cleared": "confidential" if role == "auditor" else None,
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
                if employees[employee]["supports"]:
                    edges.append((employee, "supports", f"department_{employees[employee]['supports']}"))
                if employees[employee]["cleared"]:
                    edges.append((employee, "cleared_for", f"classification_{employees[employee]['cleared']}"))

    docs: dict[str, dict] = {}
    levels, weights = zip(*CLASSIFICATIONS, strict=True)
    for department in DEPARTMENTS:
        for project in owned[department]:
            for _ in range(documents):
                # a document belongs to two projects of its department
                projects_of = [project, rng.choice([p for p in owned[department] if p != project])]
                document = f"document_D{len(docs) + 1:03d}"
                site = rng.choice(sites)
                level = rng.choices(levels, weights)[0]
                docs[document] = {
                    "department": department, "projects": projects_of, "site": site,
                    "region": site_region[site], "level": level,
                }  # fmt: skip
                nodes.append((document, "document"))
                edges += [(document, "belongs_to", p) for p in projects_of]
                edges += [
                    (document, "owned_by", f"department_{department}"),
                    (document, "stored_at", f"site_{site}"),
                    (document, "stored_in", f"region_{site_region[site]}"),
                    (document, "classified_as", f"classification_{level}"),
                ]

    permitted = {(e, d) for e in employees for d in docs if allowed(employees[e], docs[d])}
    edges += [(e, "accessed", d) for e, d in sorted(permitted)]

    scenarios, demo = _demo(employees, docs, permitted)
    return nodes, edges, scenarios, demo


def allowed(e: dict, d: dict) -> bool:
    """The current policy (demo/policy/app.rego): a project in common, or a public document
    of the employee's own department."""
    return bool(set(d["projects"]) & set(e["projects"])) or (
        d["level"] == "public" and d["department"] == e["department"]
    )


# the hidden policies: name -> (whether the employee may read the document, the expected predicates)
HIDDEN = {
    **{role: (lambda e, d, r=role: e["role"] == r and d["department"] == e["department"],
              [{"kind": "shared", "relation": "works_in", "other": "owned_by"},
               {"kind": "user_has", "relation": "holds", "other": f"role_{role}"}])
       for role in DEPARTMENT_ROLES.values()},
    "security_officer": (lambda e, d: e["role"] == "security_officer" and d["region"] == e["region"],
                         [{"kind": "shared", "relation": "based_in", "other": "stored_in"},
                          {"kind": "user_has", "relation": "holds", "other": "role_security_officer"}]),
    "facility_manager": (lambda e, d: e["role"] == "facility_manager" and d["site"] == e["site"],
                         [{"kind": "shared", "relation": "located_in", "other": "stored_at"},
                          {"kind": "user_has", "relation": "holds", "other": "role_facility_manager"}]),
    # only auditors are cleared and only HR partners support a department, so their role adds
    # nothing: the miner keeps the one predicate
    "auditor": (lambda e, d: e["role"] == "auditor" and d["level"] == e["cleared"],
                [{"kind": "shared", "relation": "cleared_for", "other": "classified_as"}]),
    "hr_partner": (lambda e, d: e["role"] == "hr_partner" and d["department"] == e["supports"],
                   [{"kind": "shared", "relation": "supports", "other": "owned_by"}]),
}  # fmt: skip


def _demo(employees: dict, docs: dict, permitted: set):
    """The appeal scenarios and demo.json: the named requests, the appeals and who reads summaries."""

    def holder(role: str, department: str | None = None, **facts) -> str:
        return next(e for e, a in employees.items() if a["role"] == role
                    and department in (None, a["department"]) and all(a[k] == v for k, v in facts.items()))  # fmt: skip

    def find(employee: str, *tests, readable: bool = False) -> str:
        """The first document the employee may (readable) or may not read now that passes a test;
        the later tests are looser, for graphs where no document passes the first."""
        for test in tests:
            found = [d for d, a in docs.items() if ((employee, d) in permitted) == readable and test(a)]
            if found:
                return found[0]
        raise ValueError(f"no document for {employee}; generate a larger graph")

    def hidden_pairs(name: str) -> list[tuple[str, str]]:
        test = HIDDEN[name][0]
        return [(e, d) for e in employees for d in docs
                if (e, d) not in permitted and test(employees[e], docs[d])]  # fmt: skip

    def of(name: str, employee: str, *tests) -> str:
        """A document the hidden policy opens for the employee, among those passing a test."""
        test = HIDDEN[name][0]
        return find(employee, *(lambda d, t=t: test(employees[employee], d) and t(d) for t in tests),
                    lambda d: test(employees[employee], d))  # fmt: skip

    e = employees
    # the appellants of the hidden policies, and a colleague in the same situation who never appeals
    sales_manager, engineering_manager = holder("manager", "sales"), holder("manager", "engineering")
    coordinator, finance_coordinator = holder("coordinator", "engineering"), holder("coordinator", "finance")
    steward, hr_steward = holder("data_steward", "finance"), holder("data_steward", "hr")
    quality, sales_quality = holder("quality_lead", "operations"), holder("quality_lead", "sales")
    officer_emea, officer_apac = holder("security_officer", region="emea"), holder("security_officer", region="apac")
    facility_jakarta, facility_frankfurt = holder("facility_manager", site="jakarta"), holder("facility_manager", site="frankfurt")
    auditor, other_auditor = [a for a in employees if e[a]["role"] == "auditor"][:2]
    partner, other_partner = holder("hr_partner", supports="engineering"), holder("hr_partner", supports="sales")
    engineer = [a for a in employees if e[a]["role"] == "engineer"][1]
    hr_analyst = holder("analyst", "hr")

    other_region = lambda a: lambda d: d["region"] != e[a]["region"]  # noqa: E731
    other_department = lambda a: lambda d: d["department"] != e[a]["department"]  # noqa: E731
    def appeal(name, scenario, user, document, admin, witness=None, witness_name=None) -> dict:
        """admin: what the admin does when the best rule is large ("accept": the expected pattern,
        "decline": only the exception); witness: a colleague in the same situation who never appeals."""
        return {"name": name, "scenario": scenario, "user": user, "document": document, "admin": admin,
                "witness": [witness, of(scenario, witness)] if witness else None, "witness_name": witness_name}  # fmt: skip

    appeals = [
        appeal("Sales manager asks for a Sales document", "manager", sales_manager,
               of("manager", sales_manager, other_region(sales_manager)), "accept",
               engineering_manager, "Engineering manager"),
        appeal("Engineering coordinator asks for an Engineering document", "coordinator", coordinator,
               of("coordinator", coordinator), "accept", finance_coordinator, "Finance coordinator"),
        appeal("Finance data steward asks for a Finance document", "data_steward", steward,
               of("data_steward", steward), "accept", hr_steward, "HR data steward"),
        appeal("Operations quality lead asks for an Operations document", "quality_lead", quality,
               of("quality_lead", quality), "accept", sales_quality, "Sales quality lead"),
        appeal("Security officer (EMEA) asks for a document stored in EMEA", "security_officer", officer_emea,
               of("security_officer", officer_emea,
                  lambda d: other_department(officer_emea)(d) and d["site"] != e[officer_emea]["site"],
                  other_department(officer_emea)),
               "accept", officer_apac, "Security officer (APAC)"),
        appeal("Facility manager (Jakarta) asks for a document stored in Jakarta", "facility_manager",
               facility_jakarta, of("facility_manager", facility_jakarta, other_department(facility_jakarta)),
               "decline", facility_frankfurt, "Facility manager (Frankfurt)"),
        appeal("Auditor asks for a confidential document of another department", "auditor", auditor,
               of("auditor", auditor, lambda d: other_department(auditor)(d) and other_region(auditor)(d),
                  other_department(auditor)),
               "accept", other_auditor, "Other auditor"),
        appeal("HR partner asks for a document of the department they support", "hr_partner", partner,
               of("hr_partner", partner, other_region(partner)), "decline", other_partner,
               "HR partner of Sales"),
        appeal("Engineer asks for a confidential document of another project", "one_off", engineer,
               find(engineer, lambda d: d["department"] == "engineering" and d["level"] == "confidential",
                    lambda d: d["level"] == "confidential"), "decline"),
        appeal("HR analyst asks for an internal Sales document", "one_off_hr", hr_analyst,
               find(hr_analyst, lambda d: d["department"] == "sales" and d["level"] == "internal",
                    lambda d: d["department"] == "sales"), "decline"),
    ]  # fmt: skip
    scenarios = [
        {"name": a["scenario"], "appeal": (a["user"], a["document"]),
         "expected": HIDDEN[a["scenario"]][1] if a["scenario"] in HIDDEN else None,
         "hidden_pairs": hidden_pairs(a["scenario"]) if a["scenario"] in HIDDEN else []}
        for a in appeals
    ]  # fmt: skip

    sales_analyst = holder("analyst", "sales")
    finance_analyst = next(a for a in employees if e[a]["role"] == "analyst" and e[a]["department"] == "finance")
    crossing = next(a for a in employees if e[a]["role"] in ("analyst", "engineer")
                    and any(not p.startswith(f"project_{e[a]['department']}") for p in e[a]["projects"]))  # fmt: skip
    own = lambda a: lambda d: d["department"] == e[a]["department"]  # noqa: E731
    # an analyst with a public document of their department that shares no project with them
    public_reader, public_doc = next(
        (a, d) for a in employees if e[a]["role"] == "analyst" for d, x in docs.items()
        if own(a)(x) and x["level"] == "public" and not set(x["projects"]) & set(e[a]["projects"])
    )  # fmt: skip
    reads = [
        # name, user, document; "expect" is the answer before any appeal
        ("Project member reads a document of their project", engineer,
         find(engineer, lambda d: bool(set(d["projects"]) & set(e[engineer]["projects"])), readable=True)),
        ("Analyst reads a public document of their department outside their projects", public_reader, public_doc),
        ("Analyst reads an internal document of their department outside their projects", sales_analyst,
         find(sales_analyst, lambda d: own(sales_analyst)(d) and d["level"] == "internal")),
        ("Employee reads a document of another department's project they work on", crossing,
         find(crossing, other_department(crossing), readable=True)),
        ("Sales analyst reads a confidential Finance document (BOLA)", sales_analyst,
         find(sales_analyst, lambda d: d["department"] == "finance" and d["level"] == "confidential",
              lambda d: d["department"] == "finance")),
        ("Engineer reads a confidential HR document (BOLA)", engineer,
         find(engineer, lambda d: d["department"] == "hr" and d["level"] == "confidential",
              lambda d: d["department"] == "hr")),
        ("Finance analyst reads a confidential Finance document outside their projects", finance_analyst,
         find(finance_analyst, lambda d: own(finance_analyst)(d) and d["level"] == "confidential")),
        ("Analyst reads a document of another department stored at their own site", hr_analyst,
         find(hr_analyst, lambda d: other_department(hr_analyst)(d) and d["site"] == e[hr_analyst]["site"])),
        *[(a["name"].replace(" asks for ", " reads "), a["user"], a["document"]) for a in appeals],
        *[(f"{a['witness_name']} (never appeals) reads what the rule of the appeal would open", *a["witness"])
          for a in appeals if a["witness"]],
    ]  # fmt: skip
    readers = [
        ("Engineer", engineer), ("Sales analyst", sales_analyst), ("Auditor", auditor),
        ("HR partner", partner), ("Facility manager (Frankfurt)", facility_frankfurt),
        ("Engineering coordinator", coordinator),
    ]  # fmt: skip
    demo = {
        "admin": ADMIN,
        "reads": [{"name": n, "user": u, "document": d, "expect": 200 if (u, d) in permitted else 403}
                  for n, u, d in reads],
        "appeals": [{**a, "expect": _expect(a["scenario"])} for a in appeals],
        "summaries": [{"name": n, "user": u} for n, u in readers],
    }  # fmt: skip
    return scenarios, demo


def _expect(scenario: str) -> str:
    if scenario.startswith("one_off"):
        return "must not generalize: only the exact exception"
    if scenario in DEPARTMENT_ROLES.values():
        return f"generalizes: every {scenario.replace('_', ' ')} reads the documents of their own department (small rule)"
    return {
        "security_officer": "generalizes: security officers read the documents stored in their region (large rule)",
        "facility_manager": "generalizes: facility managers read the documents stored at their site (large rule)",
        "auditor": "generalizes: auditors read every confidential document (large rule)",
        "hr_partner": "generalizes: HR partners read the documents of the department they support (large rule)",
    }[scenario]


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
    parser.add_argument("--teams", type=int, default=3, help="per department")
    parser.add_argument("--team-size", type=int, default=12)
    parser.add_argument("--projects", type=int, default=4, help="per department")
    parser.add_argument("--documents", type=int, default=8, help="per project")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    if args.teams < MIN_TEAMS or args.team_size < MIN_TEAM_SIZE:
        parser.error(f"needs at least {MIN_TEAMS} teams of {MIN_TEAM_SIZE} per department")
    nodes, edges, scenarios, demo = build(
        args.teams, args.team_size, args.projects, args.documents, args.seed
    )
    write(args.out_dir, nodes, edges, scenarios, demo)
    accessed = sum(e[1] == "accessed" for e in edges)
    print(f"{len(nodes)} nodes, {len(edges)} edges ({accessed} accessed) in {args.out_dir}")
    print(f"{len(scenarios)} appeal scenarios in {args.out_dir / 'scenarios.json'}")


if __name__ == "__main__":
    main()
