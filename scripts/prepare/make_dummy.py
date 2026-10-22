"""Write a small dummy campus graph (nodes.csv, edges.csv, scenarios.json) for testing appeals.

Every program has one head of program, a few lecturers, students and courses. The current policy,
recorded as "accessed" edges, is: a lecturer reads a student if they teach a course the student
takes, or advise the student. There is no head-of-program rule yet, so an appeal by a head of
program for a student of their own program should lead to that rule.

scenarios.json (see appeal_scenarios.py) holds two appeals for scripts/evaluate/evaluate_knn.py:
  head_of_program  the head of P0 asks for a P0 student; the hidden rule "head of program may read
                   students of their own program" should be found (its pairs: hidden/*.csv)
  one_off          a lecturer asks for a student of another program; nothing should generalise

This is only for tests and local experiments; the real data generator belongs to the demo repository.

Example:
    python scripts/prepare/make_dummy.py output/dummy-data
    python -m hgnn --data output/dummy-data --target-relation accessed \
        --out output/dummy --learning-rate 0.01 --patience 50
    python scripts/similar_cases.py --model-dir output/dummy \
        --user lecturer_head_P0 --object student_P0_05
    python scripts/evaluate/evaluate_knn.py --model-dir output/dummy \
        --scenarios output/dummy-data/scenarios.json
"""

import argparse
import csv
import random
from pathlib import Path

import appeal_scenarios

HEAD, LECTURER = "position_head_of_program", "position_lecturer"


def build(programs: int, lecturers: int, students: int, courses: int, seed: int):
    """Return nodes, edges and the appeal scenarios."""
    rng = random.Random(seed)
    nodes = [(HEAD, "position"), (LECTURER, "position")]
    edges = []
    head_rule = []  # (head, student of their program) pairs the current policy does not allow
    for p in range(programs):
        program = f"program_P{p}"
        nodes.append((program, "program"))
        program_courses = [f"course_P{p}_{c}" for c in range(courses)]
        for course in program_courses:
            nodes.append((course, "course"))
            edges.append((course, "belongs_to", program))

        staff = [f"lecturer_head_P{p}"] + [f"lecturer_P{p}_{i}" for i in range(lecturers)]
        teaches = {}
        for i, lecturer in enumerate(staff):
            nodes.append((lecturer, "lecturer"))
            edges.append((lecturer, "member_of", program))
            edges.append((lecturer, "holds", HEAD if i == 0 else LECTURER))
            # the head of program teaches one course, the others two
            teaches[lecturer] = [program_courses[0]] if i == 0 else rng.sample(program_courses, 2)
            edges += [(lecturer, "teaches", c) for c in teaches[lecturer]]

        for s in range(students):
            student = f"student_P{p}_{s:02d}"
            nodes.append((student, "student"))
            edges.append((student, "member_of", program))
            enrolled = rng.sample(program_courses, 2)
            edges += [(student, "enrolled_in", c) for c in enrolled]
            advisor = rng.choice(staff)
            edges.append((advisor, "advises", student))
            for lecturer in staff:
                if lecturer == advisor or set(teaches[lecturer]) & set(enrolled):
                    edges.append((lecturer, "accessed", student))
                elif lecturer == staff[0]:
                    head_rule.append((lecturer, student))

    scenarios = [
        {
            "name": "head_of_program",
            "appeal": next(pair for pair in head_rule if pair[0] == "lecturer_head_P0"),
            "expected": [
                {"kind": "shared", "relation": "member_of", "other": "member_of"},
                {"kind": "user_has", "relation": "holds", "other": HEAD},
            ],
            "hidden_pairs": head_rule,
        },
        {
            # a lecturer of the second program and a student of the last one: no relation at all
            "name": "one_off",
            "appeal": (
                f"lecturer_P1_{lecturers - 1}",
                f"student_P{programs - 1}_{students - 1:02d}",
            ),
            "expected": None,
            "hidden_pairs": [],
        },
    ]
    return nodes, edges, scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a small dummy campus graph for testing appeals.")
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--programs", type=int, default=6)
    parser.add_argument("--lecturers", type=int, default=4, help="per program, besides the head")
    parser.add_argument("--students", type=int, default=20, help="per program")
    parser.add_argument("--courses", type=int, default=4, help="per program")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    if args.programs < 2 or args.lecturers < 1:
        parser.error("needs at least 2 programs and 1 lecturer per program")
    nodes, edges, scenarios = build(
        args.programs, args.lecturers, args.students, args.courses, args.seed
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "nodes.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("id", "type"), *nodes])
    with (args.out_dir / "edges.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("src", "relation", "dst"), *edges])
    appeal_scenarios.write(args.out_dir, "accessed", False, scenarios)
    accessed = sum(e[1] == "accessed" for e in edges)
    print(f"{len(nodes)} nodes, {len(edges)} edges ({accessed} accessed) in {args.out_dir}")
    print(f"{len(scenarios)} appeal scenarios in {args.out_dir / 'scenarios.json'}")


if __name__ == "__main__":
    main()
