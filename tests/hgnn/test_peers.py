import random
from pathlib import Path

import pytest
import torch

from hgnn.graph import load_graph
from hgnn.peers import PeerIndex
from hgnn.train import TrainConfig, sample_training_pairs, split_edges, train

TOY = Path(__file__).parent / "fixtures" / "toy_graph"


@pytest.fixture
def graph():
    return load_graph(TOY, "accessed")


def _index(graph):
    return PeerIndex(graph, graph.data[graph.target].edge_index)


def _ids(graph, node_type, *names):
    return [graph.node_ids[node_type].index(n) for n in names]


def test_peer_coverage_counts_colleagues_not_the_user(graph):
    budi, andi = _ids(graph, "lecturer", "lecturer_budi", "lecturer_andi")
    (fajar,) = _ids(graph, "student", "student_fajar")

    coverage = _index(graph).coverage(torch.tensor([[budi, andi], [fajar, fajar]]))

    assert coverage[0] == pytest.approx(1 / 2)
    assert coverage[1] == pytest.approx(1 / 2)


def test_peer_coverage_is_zero_when_no_peer_has_the_object(graph):
    (sari,) = _ids(graph, "lecturer", "lecturer_sari")
    (fajar,) = _ids(graph, "student", "student_fajar")

    coverage = _index(graph).coverage(torch.tensor([[sari], [fajar]]))

    assert coverage[0] == 0.0


def test_hard_negatives_are_peers_objects_the_user_does_not_have(graph):
    index = _index(graph)
    (andi,) = _ids(graph, "lecturer", "lecturer_andi")

    hard = index.hard_negatives([andi] * 5, per_user=1, rng=random.Random(0))

    assert hard.size(1) == 5
    for user, obj in hard.t().tolist():
        assert (user, obj) not in index.known
        assert any(obj in index.owned[peer] for peer in index.owned if peer != user)


def test_training_pairs_include_hard_negatives(graph):
    torch.manual_seed(0)
    train_data, _, _ = split_edges(graph, TrainConfig())
    target = graph.target
    visible = torch.cat([train_data[target].edge_index, train_data[target].edge_label_index], 1)

    pairs, labels = sample_training_pairs(
        train_data, target, 2.0, PeerIndex(graph, visible), 1.0, random.Random(0)
    )

    positives = int(labels.sum())
    assert int((labels == 0).sum()) == 2 * positives


def test_training_runs_with_one_layer_and_hard_negatives(graph):
    config = TrainConfig(hidden=8, num_layers=1, hard_negative_ratio=0.5, max_epochs=5, seed=0)

    result = train(graph, config)

    assert 1 <= len(result.history) <= 5
    assert result.model.encode(graph.data)["lecturer"].shape == (5, 8)
