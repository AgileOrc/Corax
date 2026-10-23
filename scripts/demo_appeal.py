# Demo of the appeal flow on the dummy campus (scripts/prepare/make_dummy.py), end to end with opa.
#
# It runs AppealService, the same code the /corax/appeals endpoints call (without HTTP and JWT), on a saved
# model. Nothing is trained. Three appeals, each with the admin's choice picked by pattern, not by number:
#   1 generalise  a head of program asks for a student of their program; the admin picks
#                 "same program AND head of program"   -> small: the rule is written at once
#   2 too broad   another head of program; the admin picks "same program" only
#                 -> large: 409, nothing is written until the admin acknowledges the scope
#   3 one-off     a lecturer asks for a student of another program; the admin keeps only the exception
# Then opa evaluates the files that were written, with graph.json as data.corax.graph.
# The patterns are those of the dummy campus; other datasets are scored with scripts/evaluate/evaluate_knn.py.
#
# python scripts/demo_appeal.py --model-dir output/dummy --opa path/to/opa
# python scripts/demo_appeal.py --model-dir output/dummy --opa path/to/opa --out output/demo-appeal   (keeps the files)

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))

from appeals import AppealError, AppealService
from config import Settings
from graph import GraphData
from risk import RiskModel

HEAD = "position_head_of_program"
SAME_PROGRAM = ("shared", "member_of", "member_of")
HEAD_OF_PROGRAM = ("user_has", "holds", HEAD)
ACTION = "read"


class Campus:
    def __init__(self, graph: GraphData, model: RiskModel):
        self.graph = graph
        self.program_of = {node: facts["member_of"][0] for node, facts in graph.structure.items() if facts.get("member_of")}
        self.programs = sorted({self.program_of[u] for u in model.users if u in self.program_of})
        self.lecturers = sorted(model.users)
        self.students = sorted(model.objects)
        if len(self.programs) < 3:
            raise ValueError("needs a dummy campus with at least 3 programs")

    def is_head(self, user: str) -> bool:
        return HEAD in self.graph.structure.get(user, {}).get("holds", ())

    def head(self, program: str) -> str:
        return next(u for u in self.lecturers if self.program_of.get(u) == program and self.is_head(u))

    def lecturer(self, program: str) -> str:
        return next(u for u in self.lecturers if self.program_of.get(u) == program and not self.is_head(u))

    def student_without_access(self, user: str, program: str, skip: str | None = None) -> str:
        return next(s for s in self.students if self.program_of.get(s) == program and s != skip and not self.graph.has_access(user, s))


def pick(record: dict, wanted: set[tuple]) -> int:
    for c in record["candidates"]:
        if {(p["kind"], p["relation"], p["other"]) for p in c["predicates"]} == wanted:
            return c["index"]
    raise ValueError(f"{record['id']}: no candidate with the predicates {sorted(wanted)}")


def run_appeal(service: AppealService, title: str, user: str, obj: str, wanted: set[tuple] | None) -> dict:
    print(f"\n=== {title}: {user} -> {obj}")
    record = service.create(user, obj, ACTION, None, "demo_admin")
    print(f"  {record['id']}: exception written; candidates, narrowest first:")
    for c in record["candidates"][:4]:
        print(f"    #{c['index']} {c['users']:>4} users {c['pairs']:>5} pairs  {c['pattern']}")

    choice = pick(record, wanted) if wanted else None
    print(f"  admin picks {'#' + str(choice) if choice else 'no rule (exception only)'}")
    try:
        result = service.confirm(record["id"], choice, False, "demo_admin")
    except AppealError as error:
        scope = error.detail.get("scope", {})
        print(f"  -> {error.status}: {error.message}")
        if scope:
            print(f"     tier {scope['tier']}: {'; '.join(scope['reasons'])}")
        return {"status": error.status, "tier": scope.get("tier")}

    print(f"  -> {result['status']}")
    if "chosen" in result:
        s = result["chosen"]["scope"]
        print(f"     tier {s['tier']}: {s['users']} users, {s['pairs']} pairs, mean risk {s['mean_risk']:.2f}")
        print("     validation: " + ", ".join(f"{c['name']} {'ok' if c['ok'] else 'FAILED'}" for c in result["validation"]))
    return {"status": result["status"], "tier": result.get("chosen", {}).get("scope", {}).get("tier")}


def opa_allows(opa: str, out: Path, user: str, obj: str) -> bool:
    (out / "input.json").write_text(json.dumps({"user": {"id": user}, "resource": {"id": obj}, "action": ACTION}), encoding="utf-8")
    allowed = False
    for package in ("generated", "exceptions"):
        result = subprocess.run(
            [opa, "eval", "-f", "raw", "-d", str(out / "generated"), "-d", str(out / "data.json"), "-i", str(out / "input.json"),
             f'object.get(data.app, ["{package}", "allow"], false)'],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        allowed = allowed or result.stdout.strip() == "true"
    return allowed


def demo(model_dir: Path, opa: str, out: Path) -> bool:
    model, graph = RiskModel.load(model_dir), GraphData.load(model_dir)
    campus = Campus(graph, model)
    settings = Settings(model_dir=model_dir, opa_path=opa, generated_dir=out / "generated", appeals_dir=out / "appeals")
    service = AppealService(model, graph, settings)
    first, second, third, last = campus.programs[0], campus.programs[1], campus.programs[2], campus.programs[-1]

    head = campus.head(first)
    one = run_appeal(service, "1 generalise", head, campus.student_without_access(head, first), {SAME_PROGRAM, HEAD_OF_PROGRAM})
    head = campus.head(second)
    two = run_appeal(service, "2 too broad", head, campus.student_without_access(head, second), {SAME_PROGRAM})
    lecturer = campus.lecturer(second)
    one_off = (lecturer, campus.student_without_access(lecturer, last))
    three = run_appeal(service, "3 one-off", *one_off, None)

    (out / "data.json").write_text(json.dumps({"corax": {"graph": graph.structure}}), encoding="utf-8")
    other_head, other_lecturer = campus.head(third), campus.lecturer(third)
    student = campus.student_without_access(other_head, third)
    checks = [
        (other_head, student, True, "another head of program, who never appealed"),
        (other_lecturer, student, False, "not a head of program"),
        (other_head, campus.student_without_access(other_head, first), False, "student of another program"),
        (*one_off, True, "the exception of appeal 3"),
        (one_off[0], campus.student_without_access(one_off[0], last, skip=one_off[1]), False, "the exception covers only that pair"),
    ]
    print("\n=== OPA on the written files")
    ok = [one == {"status": "rule_applied", "tier": "small"}, two == {"status": 409, "tier": "large"}, three["status"] == "exception_only"]
    for user, obj, want, why in checks:
        got = opa_allows(opa, out, user, obj)
        ok.append(got == want)
        print(f"  {user:18} -> {obj:15} {'allow' if got else 'deny ':5}  {'✓' if got == want else '✗'}  {why}")

    rule = next((out / "generated").glob("*-rule.rego"), None)
    if rule:
        print(f"\n=== {rule.name}\n{rule.read_text(encoding='utf-8')}")
    print(f"{sum(ok)}/{len(ok)} expectations met")
    return all(ok)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run three appeals on the dummy campus end to end and check the written Rego with opa.")
    parser.add_argument("--model-dir", required=True, type=Path, help="folder written by python -m hgnn from scripts/prepare/make_dummy.py data")
    parser.add_argument("--opa", default="opa", help="opa binary (default: opa on PATH)")
    parser.add_argument("--out", type=Path, help="keep the Rego files and appeal records here (default: a temporary folder)")
    args = parser.parse_args()

    if args.out and args.out.exists() and any(args.out.iterdir()):
        parser.error(f"{args.out} is not empty")
    try:
        if args.out:
            ok = demo(args.model_dir, args.opa, args.out)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                ok = demo(args.model_dir, args.opa, Path(tmp))
    except (ValueError, AppealError, RuntimeError) as error:
        parser.error(str(error))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    # Windows consoles default to cp1252, which cannot print ✓ and ✗
    sys.stdout.reconfigure(encoding="utf-8")
    main()
