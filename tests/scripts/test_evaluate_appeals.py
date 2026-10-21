import subprocess
import sys
from pathlib import Path

from evaluate_appeals import coverage, precision_at_k, rank_of
from patterns import Candidate, Predicate

ROOT = Path(__file__).parents[2]
HEAD = Predicate("user_has", "holds", "head")
SAME = Predicate("shared", "member_of", "member_of")


def candidate(*predicates, pairs=1):
    return Candidate(predicates, users=1, pairs=pairs, estimated=False, support=0.0, examples=())


def test_precision_at_k_counts_hidden_neighbours():
    neighbours = [("a", "x"), ("b", "y"), ("c", "z"), ("d", "w")]

    assert precision_at_k(neighbours, {("b", "y"), ("d", "w"), ("e", "v")}) == 0.5
    assert precision_at_k([], {("b", "y")}) == 0.0


def test_rank_ignores_predicate_order():
    found = [candidate(SAME), candidate(HEAD), candidate(SAME, HEAD)]

    assert rank_of(found, (HEAD, SAME)) == 3
    assert rank_of(found, (HEAD,)) == 2
    assert rank_of(found, (Predicate("direct", "advises"),)) is None


def test_coverage_of_a_candidate():
    structure = {
        "budi": {"holds": ["head"], "member_of": ["IF"]},
        "sari": {"holds": ["head"], "member_of": ["SI"]},
        "andi": {"member_of": ["IF"]},
        "ani": {"member_of": ["IF"]},
        "dewi": {"member_of": ["SI"]},
    }
    hidden = {("sari", "dewi"), ("budi", "ani"), ("andi", "ani")}

    covered, precision = coverage(structure, candidate(HEAD, pairs=4), hidden)

    assert covered == 2 / 3
    assert precision == 2 / 4


def test_command_line_on_a_tiny_campus(tmp_path):
    data, model = tmp_path / "data", tmp_path / "model"

    def run(*args):
        completed = subprocess.run(
            [sys.executable, *map(str, args)], capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0, completed.stderr
        return completed.stdout

    run(ROOT / "scripts/make_mini_campus.py", data, "--programs", "3", "--students", "8")
    run(
        ROOT / "hgnn-job/run.py", "--data", data, "--target-relation", "accessed",
        "--out", model, "--hidden", "16", "--max-epochs", "20",
    )
    out = run(
        ROOT / "scripts/evaluate_appeals.py", "--model-dir", model,
        "--scenarios", data / "scenarios.json", "--out", tmp_path / "results.json",
    )

    assert "head_of_program" in out
    assert "one_off" in out
    assert (tmp_path / "results.json").exists()
