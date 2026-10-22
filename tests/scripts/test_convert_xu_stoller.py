import json

import appeal_scenarios
import convert_xu_stoller as c
import pytest

SAMPLE = """# a tiny policy in the .abac format, written for these tests
userAttrib(chair1, isChair=True, department=d1)
userAttrib(fac1, position=faculty, department=d1, crsTaught={k1 })
userAttrib(stu1, position=student, department=d1, crsTaken={k1 })
userAttrib(stu2, position=student, department=d2, crsTaken={k2 })
userAttrib(reg1, department=registrar)
resourceAttrib(gb1, type=gradebook, department=d1, crs=k1)
resourceAttrib(tr1, type=transcript, student=stu1, department=d1)
resourceAttrib(tr2, type=transcript, student=stu2, department=d2)
rule(; type in {gradebook}; {read}; crsTaken ] crs)
rule(isChair [ {True}; type [ {transcript}; {read}; department=department)
rule(; type in {transcript}; {read}; uid=student;)
rule(department in {registrar}; type in {transcript}; {read}; )
unremovableResourceAttribs(type)
"""


@pytest.fixture
def policy():
    return c.parse(SAMPLE)


def test_parse_reads_users_resources_and_rules(policy):
    assert len(policy.users) == 5
    assert len(policy.resources) == 3
    assert len(policy.rules) == 4
    assert policy.users["fac1"]["crsTaught"] == ["k1"]
    assert policy.users["chair1"]["isChair"] == "true"
    assert policy.rules[1].subject == [("isChair", "[", ["true"])]
    assert policy.rules[2].constraints == [("uid", "=", "student")]


def test_each_rule_grants_the_hand_counted_pairs(policy):
    granted = [c.permitted(policy, rule) for rule in policy.rules]

    assert granted == [
        {("stu1", "gb1")},
        {("chair1", "tr1")},
        {("stu1", "tr1"), ("stu2", "tr2")},
        {("reg1", "tr1"), ("reg1", "tr2")},
    ]


def test_attributes_with_shared_values_share_value_nodes(policy):
    label = c.domains(policy, c.user_references(policy))

    assert label["crsTaken"] == label["crsTaught"] == label["crs"] == "crs"
    assert c.user_references(policy) == {"student"}


def test_graph_edges_and_the_reverse_reference(policy):
    nodes, edges, _, _, _, _ = c.build(policy)

    assert nodes["crs_k1"] == "value_crs"
    assert nodes["type_transcript"] == "value_type"
    assert ("user_fac1", "crsTaught", "crs_k1") in edges
    assert ("res_gb1", "crs", "crs_k1") in edges
    assert ("res_tr1", "student", "user_stu1") in edges
    assert ("user_stu1", "student_of", "res_tr1") in edges


def test_hiding_a_rule_removes_only_its_own_pairs(policy):
    _, edges, _, hidden, _, _ = c.build(policy, hidden_rule=2)

    accessed = {(s, d) for s, r, d in edges if r == c.TARGET}
    assert hidden == {("chair1", "tr1")}
    assert ("user_chair1", "res_tr1") not in accessed
    assert ("user_stu1", "res_tr1") in accessed
    assert len(accessed) == 5


def test_rules_become_corax_predicates(policy):
    label, refs = c.domains(policy, {"student"}), {"student"}

    assert c.predicates(policy.rules[0], label, refs) == [
        {"kind": "object_has", "relation": "type", "other": "type_gradebook"},
        {"kind": "shared", "relation": "crsTaken", "other": "crs"},
    ]
    assert c.predicates(policy.rules[1], label, refs) == [
        {"kind": "user_has", "relation": "isChair", "other": "isChair_true"},
        {"kind": "object_has", "relation": "type", "other": "type_transcript"},
        {"kind": "shared", "relation": "department", "other": "department"},
    ]
    assert c.predicates(policy.rules[2], label, refs) == [
        {"kind": "object_has", "relation": "type", "other": "type_transcript"},
        {"kind": "direct", "relation": "student_of", "other": ""},
    ]


@pytest.mark.parametrize(
    "line",
    [
        "rule(department in {registrar admissions}; type in {transcript}; {read}; )",
        "rule(; type in {gradebook}; {read}; crsTaken > crs)",
    ],
)
def test_rules_outside_the_vocabulary_are_marked_inexpressible(line):
    policy = c.parse(SAMPLE + line + "\n")

    assert c.predicates(policy.rules[-1], c.domains(policy, {"student"}), {"student"}) is None


def test_write_produces_a_scenario_for_the_hidden_rule(policy, tmp_path):
    summary = c.write(tmp_path, policy, hidden_rule=2)

    assert summary["hidden"] == 1 and summary["expressible"]
    scenarios = appeal_scenarios.load(tmp_path / "scenarios.json")
    assert scenarios.object_values is True and scenarios.max_size == 3
    assert scenarios.scenarios[0].appeal == ("user_chair1", "res_tr1")
    assert scenarios.scenarios[0].hidden == {("user_chair1", "res_tr1")}


def test_all_rules_writes_one_data_folder_per_rule_with_hidden_pairs(policy, tmp_path):
    written = c.write_all(tmp_path, policy)

    assert sorted(written) == [1, 2, 3, 4]
    assert all(summary is not None for summary in written.values())
    for index in written:
        scenarios = appeal_scenarios.load(tmp_path / f"rule_{index:02d}" / "data" / "scenarios.json")
        assert scenarios.scenarios[0].name == f"rule_{index:02d}"


def test_all_rules_skips_a_rule_another_rule_already_covers(tmp_path):
    policy = c.parse(SAMPLE + "rule(; type in {transcript}; {read}; uid=student;)\n")

    written = c.write_all(tmp_path, policy)

    assert written[3] is None and written[5] is None
    assert not (tmp_path / "rule_03").exists()


def test_old_scenario_files_keep_the_defaults(tmp_path):
    (tmp_path / "scenarios.json").write_text(
        json.dumps({"target_relation": "accessed", "scenarios": []}), encoding="utf-8"
    )

    loaded = appeal_scenarios.load(tmp_path / "scenarios.json")

    assert (loaded.object_values, loaded.max_size) == (False, 2)
