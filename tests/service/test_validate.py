import pytest
from patterns import Predicate, opened_pairs
from rules import render_exception, render_rule
from validate import expected_decisions, validate, whitelist_problems, write_atomic

GRAPH = {
    "budi": {"holds": ["head"], "member_of": ["IF"]},
    "sari": {"holds": ["head"], "member_of": ["SI"]},
    "andi": {"holds": ["lecturer"], "member_of": ["IF"]},
    "ani": {"member_of": ["IF"]},
    "candra": {"member_of": ["IF"]},
    "dewi": {"member_of": ["SI"]},
}
USERS, OBJECTS = ["budi", "sari", "andi"], ["ani", "candra", "dewi"]
ACCESS = {"budi": frozenset({"ani"})}
APPEAL = ("budi", "candra")
HEAD_RULE = (Predicate("shared", "member_of", "member_of"), Predicate("user_has", "holds", "head"))


def expected_for(predicates):
    opened = opened_pairs(GRAPH, ACCESS, APPEAL, USERS, OBJECTS, predicates)
    return expected_decisions(GRAPH, predicates, opened, USERS, OBJECTS, APPEAL, others=50)


def check(rego, opa, package="app.generated", expected=None, policy_dir=None):
    expected = expected if expected is not None else expected_for(HEAD_RULE)
    return validate(rego, package, "read", GRAPH, expected, opa, policy_dir)


def names(report):
    return [(c.name, c.ok) for c in report.checks]


def test_opened_pairs_skip_access_and_the_appeal():
    assert opened_pairs(GRAPH, ACCESS, APPEAL, USERS, OBJECTS, HEAD_RULE) == [("sari", "dewi")]


def test_opened_pairs_for_user_only_conditions():
    pairs = opened_pairs(
        GRAPH, ACCESS, APPEAL, USERS, OBJECTS, [Predicate("user_has", "holds", "head")]
    )

    assert sorted(pairs) == [
        ("budi", "dewi"),
        ("sari", "ani"),
        ("sari", "candra"),
        ("sari", "dewi"),
    ]


def test_expected_decisions_cover_the_appeal_and_opened_pairs():
    expected = expected_for(HEAD_RULE)

    assert expected[APPEAL] is True
    assert expected[("sari", "dewi")] is True
    assert all(v == (p in {APPEAL, ("sari", "dewi"), ("budi", "ani")}) for p, v in expected.items())


def test_generated_rule_passes_every_check(opa):
    report = check(render_rule("appeal-0001", "read", HEAD_RULE), opa)

    assert report.ok, report.checks
    assert names(report) == [
        ("syntax", True),
        ("whitelist", True),
        ("app tests", True),
        ("equivalence", True),
    ]


def test_exception_passes_every_check(opa):
    expected = {p: p == APPEAL for p in expected_for(HEAD_RULE)}

    report = check(render_exception("appeal-0001", *APPEAL[:1], "read", APPEAL[1]), opa,
                   package="app.exceptions", expected=expected)

    assert report.ok, report.checks


def test_rule_that_allows_more_than_the_pattern_fails_equivalence(opa):
    broader = render_rule("appeal-0001", "read", HEAD_RULE).replace('\t"head" in', '\t# "head" in')

    report = check(broader, opa)

    assert not report.ok
    assert report.checks[-1].name == "equivalence"
    assert "andi" in report.checks[-1].detail


def test_syntax_error_stops_at_the_first_check(opa):
    report = check(
        render_rule("appeal-0001", "read", HEAD_RULE).replace("allow if {", "allow {{"), opa
    )

    assert names(report) == [("syntax", False)]


@pytest.mark.parametrize(
    "extra",
    [
        "\tdata.secrets.token == input.action",
        '\tinput.headers.x == "1"',
        '\thttp.send({"url": "http://x"})',
    ],
)
def test_references_outside_the_whitelist_are_rejected(opa, extra):
    rego = render_rule("appeal-0001", "read", HEAD_RULE).replace(
        '\tinput.action == "read"', f'\tinput.action == "read"\n{extra}'
    )

    report = check(rego, opa)

    assert names(report)[:2] == [("syntax", True), ("whitelist", False)]


def test_wrong_package_and_rule_names_are_rejected():
    ast = {
        "package": {
            "path": [
                {"type": "var", "value": "data"},
                {"type": "string", "value": "app"},
                {"type": "string", "value": "authz"},
            ]
        },
        "rules": [
            {"head": {"name": "deny", "value": {"type": "boolean", "value": True}}, "body": []},
            {
                "default": True,
                "head": {"name": "allow", "value": {"type": "boolean", "value": True}},
                "body": [],
            },
        ],
    }

    problems = whitelist_problems(ast, "app.generated")

    assert any("package app.authz" in p for p in problems)
    assert any("found deny" in p for p in problems)
    assert any("default" in p for p in problems)


def test_application_tests_must_still_pass(opa, tmp_path):
    (tmp_path / "app_test.rego").write_text(
        "package app.authz_test\n\ntest_fails if {\n\tfalse\n}\n", encoding="utf-8"
    )

    report = check(render_rule("appeal-0001", "read", HEAD_RULE), opa, policy_dir=tmp_path)

    assert names(report) == [("syntax", True), ("whitelist", True), ("app tests", False)]


def test_write_atomic_replaces_the_file(tmp_path):
    write_atomic(tmp_path, "appeal-0001-rule.rego", "old")
    path = write_atomic(tmp_path, "appeal-0001-rule.rego", "new")

    assert path.read_text(encoding="utf-8") == "new"
    assert [p.name for p in tmp_path.iterdir()] == ["appeal-0001-rule.rego"]
