import json
import os
import random
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

Pair = tuple[str, str]

PACKAGES = {"app.generated", "app.exceptions"}
INPUT_REFS = {("action",), ("user", "id"), ("resource", "id")}
OPERATORS = {("equal",), ("internal", "member_2")}
TERM_TYPES = {"ref", "var", "string", "call", "boolean"}

@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""

@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(Check(name, ok, detail))
        return ok

def validate(
    rego: str,
    package: str,
    action: str,
    graph: Mapping[str, Mapping[str, list[str]]],
    expected: Mapping[Pair, bool],
    opa: str = "opa",
    policy_dir: str | Path | None = None,
) -> Report:
    report = Report()
    with tempfile.TemporaryDirectory() as tmp:
        rule_file = Path(tmp) / "candidate.rego"
        rule_file.write_text(rego, encoding="utf-8")

        result = _run([opa, "check", "--strict", str(rule_file)])
        if not report.add("syntax", result.returncode == 0, result.stderr.strip()):
            return report

        result = _run([opa, "parse", "--format", "json", str(rule_file)])
        problems = whitelist_problems(json.loads(result.stdout), package)
        if not report.add("whitelist", not problems, "; ".join(problems)):
            return report

        if policy_dir is None:
            report.add("app tests", True, "skipped: no policy folder")
        else:
            result = _run([opa, "test", str(policy_dir), str(rule_file)])
            output = (result.stdout + result.stderr).strip().splitlines()
            if not report.add("app tests", result.returncode == 0, output[-1] if output else ""):
                return report

        allowed = _evaluate(opa, rule_file, Path(tmp), package, action, graph, expected)
        wrong = sorted(pair for pair, want in expected.items() if (pair in allowed) != want)
        detail = f"{len(expected)} pairs" if not wrong else f"{len(wrong)} differ, e.g. {wrong[:3]}"
        report.add("equivalence", not wrong, detail)
    return report

def expected_decisions(
    structure,
    predicates,
    opened: list[Pair],
    users: list[str],
    objects: list[str],
    appeal: Pair,
    max_opened: int = 2000,
    others: int = 500,
    seed: int = 0,
) -> dict[Pair, bool]:
    rng = random.Random(seed)
    pairs = {appeal, *(opened if len(opened) <= max_opened else rng.sample(opened, max_opened))}
    pairs.update((rng.choice(users), rng.choice(objects)) for _ in range(others))
    return {pair: all(p.holds(structure, *pair) for p in predicates) for pair in pairs}

def whitelist_problems(ast: dict, package: str) -> list[str]:
    problems = []
    path = [t["value"] for t in ast["package"]["path"][1:]]
    if ".".join(path) != package or package not in PACKAGES:
        problems.append(f"package {'.'.join(path)} is not {package}")
    if ast.get("imports"):
        problems.append("imports are not allowed")
    for rule in ast.get("rules", []):
        head = rule["head"]
        if head.get("name") != "allow" or head.get("value") != {"type": "boolean", "value": True}:
            problems.append(f"only `allow if {{...}}` rules are allowed, found {head.get('name')}")
        if rule.get("default") or rule.get("else"):
            problems.append("default and else are not allowed")
        for term in _terms(rule["body"]):
            problem = _term_problem(term)
            if problem:
                problems.append(problem)
    return sorted(set(problems))

def _terms(node) -> Iterable[dict]:
    if isinstance(node, dict):
        if "type" in node:
            yield node
        for value in node.values():
            yield from _terms(value)
    elif isinstance(node, list):
        for value in node:
            yield from _terms(value)

def _term_problem(term: dict) -> str | None:
    if term["type"] not in TERM_TYPES:
        return f"{term['type']} terms are not allowed"
    if term["type"] != "ref":
        return None
    head, *rest = term["value"]
    names = tuple(t["value"] for t in rest if t["type"] == "string")
    if head["value"] == "input" and names in INPUT_REFS and len(names) == len(rest):
        return None
    if head["value"] in {"equal", "internal"} and (head["value"], *names) in OPERATORS:
        return None
    if head["value"] == "data":
        if (
            len(rest) == 4
            and [t.get("value") for t in rest[:2]] == ["corax", "graph"]
            and rest[2]["type"] == "ref"
            and rest[3]["type"] == "string"
        ):
            return None
    if head["type"] == "var" and not rest and head["value"] not in {"data", "input"}:
        return None
    text = ".".join(str(t.get("value")) for t in term["value"])
    return f"reference {text} is not allowed"

def _evaluate(opa, rule_file, tmp, package, action, graph, expected) -> set[Pair]:
    pairs = sorted(expected)
    nodes = {n for pair in pairs for n in pair}
    data = {
        "corax": {"graph": {n: graph[n] for n in nodes if n in graph}},
        "validation": {"pairs": [list(p) for p in pairs], "action": action},
    }
    data_file = tmp / "data.json"
    data_file.write_text(json.dumps(data), encoding="utf-8")
    helper = tmp / "validation.rego"
    helper.write_text(
        "package validation\n\n"
        "allowed contains [u, o] if {\n"
        "\tsome [u, o] in data.validation.pairs\n"
        f"\tdata.{package}.allow with input as "
        '{"user": {"id": u}, "resource": {"id": o}, "action": data.validation.action}\n'
        "}\n",
        encoding="utf-8",
    )
    files = ["-d", str(rule_file), "-d", str(helper), "-d", str(data_file)]
    result = _run([opa, "eval", "--format", "json", *files, "data.validation.allowed"])
    if result.returncode != 0:
        raise RuntimeError(f"opa eval failed: {result.stderr.strip()}")
    value = json.loads(result.stdout)["result"][0]["expressions"][0]["value"]
    return {tuple(p) for p in value}

def _run(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, check=False, timeout=120)

def write_atomic(folder: str | Path, name: str, text: str) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    temporary = folder / f".{name}.tmp"
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)
    return target