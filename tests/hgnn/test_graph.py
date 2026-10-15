from pathlib import Path

import pytest
from corax_hgnn.graph import load_graph

TOY = Path(__file__).parent / "fixtures" / "toy_graph"


def test_loads_node_types_and_counts():
    graph = load_graph(TOY, "accessed")

    assert set(graph.node_ids) == {"lecturer", "student", "program", "position", "course"}
    assert graph.data["lecturer"].num_nodes == 5
    assert graph.data["student"].num_nodes == 6
    # node ids keep file order, so row i of an embedding matrix is node_ids[type][i]
    assert graph.node_ids["lecturer"][0] == "lecturer_budi"


def test_target_edge_type_and_its_reverse():
    graph = load_graph(TOY, "accessed")

    assert graph.target == ("lecturer", "accessed", "student")
    assert graph.target_reverse == ("student", "rev_accessed", "lecturer")
    forward = graph.data[graph.target].edge_index
    reverse = graph.data[graph.target_reverse].edge_index
    assert forward.shape == (2, 10)
    assert reverse.shape == (2, 10)


def test_same_relation_name_between_different_types_gives_two_edge_types():
    graph = load_graph(TOY, "accessed")

    assert ("lecturer", "member_of", "program") in graph.data.edge_types
    assert ("student", "member_of", "program") in graph.data.edge_types


def _write(folder: Path, nodes: str, edges: str) -> Path:
    (folder / "nodes.csv").write_text(nodes, encoding="utf-8")
    (folder / "edges.csv").write_text(edges, encoding="utf-8")
    return folder


def test_unknown_node_in_edges_is_rejected(tmp_path):
    folder = _write(tmp_path, "id,type\nu1,user\n", "src,relation,dst\nu1,access,ghost\n")

    with pytest.raises(ValueError, match="unknown node 'ghost'"):
        load_graph(folder, "access")


def test_duplicate_node_id_is_rejected(tmp_path):
    folder = _write(tmp_path, "id,type\nu1,user\nu1,user\n", "src,relation,dst\n")

    with pytest.raises(ValueError, match="duplicate node id"):
        load_graph(folder, "access")


def test_missing_target_relation_is_rejected(tmp_path):
    folder = _write(tmp_path, "id,type\nu1,user\nr1,res\n", "src,relation,dst\nu1,view,r1\n")

    with pytest.raises(ValueError, match="exactly one pair"):
        load_graph(folder, "access")


def test_node_type_without_edges_is_rejected(tmp_path):
    folder = _write(
        tmp_path,
        "id,type\nu1,user\nr1,res\nx1,lonely\n",
        "src,relation,dst\nu1,access,r1\n",
    )

    with pytest.raises(ValueError, match="without any edge"):
        load_graph(folder, "access")
