import json

import pytest
from describe import Labels, describe_exception, describe_rule
from graph import GraphData
from patterns import Predicate

RELATION_TYPES = {"member_of": "department", "holds": "role", "owns": "report"}
SAME_DEPARTMENT = Predicate("shared", "member_of", "member_of")
MANAGER = Predicate("user_has", "holds", "role_manager")


def rule(*predicates, labels=None):
    return describe_rule(predicates, "read_report", "employee", "report", RELATION_TYPES, labels)


def test_without_labels_the_ids_are_used():
    assert rule(SAME_DEPARTMENT, MANAGER) == (
        "An employee may read_report a report when the employee and the report have the same department "
        "and the employee holds role manager."
    )


def test_labels_make_the_sentence_readable():
    labels = Labels(
        actions={"read_report": "read"},
        relations={"holds": "is a"},
        nodes={"role_manager": "manager"},
    )

    assert rule(SAME_DEPARTMENT, MANAGER, labels=labels) == (
        "An employee may read a report when the employee and the report have the same department "
        "and the employee is a manager."
    )


@pytest.mark.parametrize(
    ("predicate", "condition"),
    [
        (Predicate("object_has", "type", "invoice"), "the report type invoice"),
        (Predicate("direct", "owns"), "the employee owns the report"),
        (Predicate("object_is", "", "report_42"), "the report is report 42"),
        (Predicate("shared", "member_of", "belongs_to"), "the employee's member of matches the report's belongs to"),
        (Predicate("user_has", "works_on", "project_1"), "the employee works on project 1"),
    ],
)
def test_every_kind_of_predicate(predicate, condition):
    assert rule(predicate).endswith(f" when {condition}.")


def test_three_conditions_are_joined_with_commas():
    sentence = rule(SAME_DEPARTMENT, MANAGER, Predicate("direct", "owns"))

    assert "department, the employee holds role manager, and the employee owns the report." in sentence


@pytest.mark.parametrize(
    ("node", "readable"),
    [("employee_E012", "employee E012"), ("document_D003", "document D003"), ("project_marketing1", "project marketing 1")],
)
def test_ids_without_a_label_stay_readable(node, readable):
    assert Labels().node(node) == readable


def test_exception_names_the_one_object():
    assert describe_exception("alice", "read_report", "report_105", "report") == (
        "alice may read_report report 105, an exception for this one report only."
    )


def test_labels_are_read_from_the_corax_config(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"corax": {"config": {"labels": {"actions": {"read_report": "read"}, "types": 3}}}}))

    labels = Labels.load(path)

    assert labels.action("read_report") == "read"
    assert labels.type("report") == "report"


@pytest.mark.parametrize("content", ["not json", "{}", '{"corax": {"config": {"labels": []}}}'])
def test_missing_or_broken_labels_fall_back_to_ids(tmp_path, content):
    path = tmp_path / "data.json"
    path.write_text(content)

    assert Labels.load(path) == Labels()
    assert Labels.load(None) == Labels()


def test_relation_types_come_from_node_ids(tmp_path):
    (tmp_path / "graph.json").write_text(json.dumps({"alice": {"member_of": ["sales"], "holds": ["unknown"]}}))
    (tmp_path / "access.json").write_text("{}")
    (tmp_path / "node_ids.json").write_text(json.dumps({"employee": ["alice"], "department": ["sales"]}))

    assert GraphData.load(tmp_path).relation_types() == {"member_of": "department"}
