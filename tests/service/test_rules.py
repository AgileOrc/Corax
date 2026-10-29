import json
import subprocess

import pytest
from patterns import Predicate
from rules import conditions, render_exception, render_rule

HEAD_RULE = (
    Predicate("shared", "member_of", "member_of"),
    Predicate("user_has", "holds", "position_head_of_program"),
)


def test_each_predicate_becomes_rego():
    lines = conditions(
        [
            Predicate("user_has", "holds", "head"),
            Predicate("object_has", "member_of", "IF"),
            Predicate("shared", "member_of", "member_of"),
            Predicate("shared", "teaches", "enrolled_in"),
            Predicate("direct", "advises"),
            Predicate("object_is", "", "PERMGROUP_1"),
        ]
    )

    assert lines == [
        '"head" in data.corax.graph[input.user.id]["holds"]',
        '"IF" in data.corax.graph[input.resource.id]["member_of"]',
        'some n1 in data.corax.graph[input.user.id]["member_of"]',
        'n1 in data.corax.graph[input.resource.id]["member_of"]',
        'some n2 in data.corax.graph[input.user.id]["teaches"]',
        'n2 in data.corax.graph[input.resource.id]["enrolled_in"]',
        'input.resource.id in data.corax.graph[input.user.id]["advises"]',
        'input.resource.id == "PERMGROUP_1"',
    ]


def test_rule_file():
    rego = render_rule("appeal-0001", "read_grades", HEAD_RULE, {"users": 6, "tier": "large"})

    assert rego == "\n".join(
        [
            "package app.generated",
            "",
            "# METADATA",
            '# title: "appeal-0001"',
            '# description: "user.member_of = object.member_of AND user holds '
            'position_head_of_program"',
            "# custom:",
            '#   appeal_id: "appeal-0001"',
            "#   users: 6",
            '#   tier: "large"',
            "allow if {",
            '\tinput.action == "read_grades"',
            '\tsome n1 in data.corax.graph[input.user.id]["member_of"]',
            '\tn1 in data.corax.graph[input.resource.id]["member_of"]',
            '\t"position_head_of_program" in data.corax.graph[input.user.id]["holds"]',
            "}",
            "",
        ]
    )


def test_exception_file_names_only_the_approved_pair():
    rego = render_exception("appeal-0001", "lecturer_budi", "read_grades", "student_candra")

    assert rego.startswith("package app.exceptions\n")
    assert '\tinput.user.id == "lecturer_budi"' in rego
    assert '\tinput.resource.id == "student_candra"' in rego
    assert '\tinput.action == "read_grades"' in rego


SNEAKY = 'x"\n\ttrue\n}\nallow if {\n\t"'


def test_ids_cannot_inject_rego():
    rego = render_exception("appeal-0001", SNEAKY, "read_grades", "student_candra")

    assert [line for line in rego.splitlines() if line.startswith("allow")] == ["allow if {"]
    assert '\tinput.user.id == "x\\"\\n\\ttrue\\n}\\nallow if {\\n\\t\\""' in rego


def test_injected_id_still_parses_as_one_rule(opa, tmp_path):
    path = tmp_path / "exception.rego"
    path.write_text(render_exception("appeal-0001", SNEAKY, "read", "o"), encoding="utf-8")

    result = subprocess.run(
        [opa, "parse", "--format", "json", str(path)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)["rules"]) == 1


@pytest.mark.parametrize("appeal_id", ["", "../etc", "a b", "x" * 65, "appeal.rego"])
def test_appeal_id_must_be_a_safe_file_name(appeal_id):
    with pytest.raises(ValueError, match="invalid appeal id"):
        render_rule(appeal_id, "read", HEAD_RULE)


def test_generated_files_pass_opa_check(opa, tmp_path):
    (tmp_path / "rule.rego").write_text(render_rule("appeal-0001", "read", HEAD_RULE))
    (tmp_path / "exception.rego").write_text(render_exception("appeal-0001", "u", "read", "o"))

    result = subprocess.run(
        [opa, "check", "--strict", str(tmp_path)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


def test_rule_and_exception_can_be_limited_to_a_resource_type():
    rule = render_rule("appeal-0001", "read_grades", HEAD_RULE, resource_type="student")
    exception = render_exception(
        "appeal-0001", "lecturer_budi", "read_grades", "student_candra", "student"
    )

    assert rule.splitlines()[-6:-4] == [
        '\tinput.action == "read_grades"',
        '\tinput.resource.type == "student"',
    ]
    assert '\tinput.resource.type == "student"' in exception
    assert "input.resource.type" not in render_rule("appeal-0001", "read_grades", HEAD_RULE)
