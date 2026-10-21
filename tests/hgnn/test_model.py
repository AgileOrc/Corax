from pathlib import Path

import pytest
import torch
from corax_hgnn.graph import load_graph
from corax_hgnn.model import HGNN, link_logits, link_probability

TOY = Path(__file__).parent / "fixtures" / "toy_graph"


@pytest.fixture
def graph():
    return load_graph(TOY, "accessed")


def test_encode_returns_one_vector_per_node(graph):
    torch.manual_seed(0)
    model = HGNN(graph.data, hidden=16)

    h = model.encode(graph.data)

    assert set(h) == set(graph.data.node_types)
    for node_type in graph.data.node_types:
        assert h[node_type].shape == (graph.data[node_type].num_nodes, 16)


def test_link_logits_is_the_dot_product(graph):
    torch.manual_seed(0)
    model = HGNN(graph.data, hidden=16)
    h = model.encode(graph.data)
    src, _, dst = graph.target
    pairs = torch.tensor([[0, 1], [2, 3]])

    logits = link_logits(h[src], h[dst], pairs)

    expected = torch.stack([h[src][0] @ h[dst][2], h[src][1] @ h[dst][3]])
    assert torch.allclose(logits, expected)


def test_link_probability_is_between_0_and_1(graph):
    torch.manual_seed(0)
    model = HGNN(graph.data, hidden=16)
    h = model.encode(graph.data)
    src, _, dst = graph.target

    p = link_probability(h[src], h[dst], graph.data[graph.target].edge_index)

    assert ((p >= 0) & (p <= 1)).all()


def test_gradients_reach_every_node_type(graph):
    torch.manual_seed(0)
    model = HGNN(graph.data, hidden=16)
    h = model.encode(graph.data)
    src, _, dst = graph.target

    logits = link_logits(h[src], h[dst], graph.data[graph.target].edge_index)
    logits.sum().backward()

    for node_type in graph.data.node_types:
        assert model.node_embeddings[node_type].weight.grad is not None


def test_same_seed_gives_same_vectors(graph):
    torch.manual_seed(42)
    first = HGNN(graph.data, hidden=16).encode(graph.data)
    torch.manual_seed(42)
    second = HGNN(graph.data, hidden=16).encode(graph.data)

    for node_type in graph.data.node_types:
        assert torch.equal(first[node_type], second[node_type])
