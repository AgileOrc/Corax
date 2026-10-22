import csv

from convert_amazon import TARGET_RELATION, convert

from hgnn.graph import load_graph

SAMPLE = """\
HOST_1,PERMGROUP_7,PERSON_BUSINESS_TITLE,PERSON_DEPTNAME,PERSON_ID,PERSON_MGR_ID,SYSTEM_SUPPORT_3
1,0,10,5,100,9,1
0,1,10,6,101,9,0
1,1,11,5,102,8,0
"""


def _read(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _convert(tmp_path):
    source = tmp_path / "amazon.csv"
    source.write_text(SAMPLE, encoding="utf-8")
    counts = convert(source, tmp_path / "graph")
    return counts, tmp_path / "graph"


def test_counts_nodes_and_edges(tmp_path):
    counts, _ = _convert(tmp_path)

    assert counts["nodes"] == {
        "resource": 3,
        "user": 3,
        "department": 2,
        "title": 2,
        "manager": 2,
    }
    assert counts["edges"][TARGET_RELATION] == 5
    assert counts["edges"]["belongs_to"] == 3


def test_access_cells_become_target_edges(tmp_path):
    _, out = _convert(tmp_path)

    access = {
        (e["src"], e["dst"]) for e in _read(out / "edges.csv") if e["relation"] == TARGET_RELATION
    }

    assert access == {
        ("user_100", "resource_HOST_1"),
        ("user_100", "resource_SYSTEM_SUPPORT_3"),
        ("user_101", "resource_PERMGROUP_7"),
        ("user_102", "resource_HOST_1"),
        ("user_102", "resource_PERMGROUP_7"),
    }


def test_output_loads_as_a_corax_graph(tmp_path):
    _, out = _convert(tmp_path)

    graph = load_graph(out, TARGET_RELATION)

    assert graph.target == ("user", TARGET_RELATION, "resource")
    assert set(graph.data.node_types) == {"user", "resource", "department", "title", "manager"}
