from pathlib import Path

import pytest
import torch
from corax_hgnn.graph import load_graph
from corax_hgnn.train import TrainConfig, roc_auc, split_edges, train

TOY = Path(__file__).parent / "fixtures" / "toy_graph"

# A higher learning rate and a smaller model keep the toy-graph tests fast.
FAST = TrainConfig(hidden=16, learning_rate=0.01, max_epochs=200, patience=10, seed=0)


@pytest.fixture
def graph():
    return load_graph(TOY, "accessed")


# --- roc_auc --------------------------------------------------------------


def test_auc_perfect_separation_is_1():
    labels = torch.tensor([0.0, 0.0, 1.0, 1.0])
    assert roc_auc(labels, torch.tensor([0.1, 0.2, 0.8, 0.9])) == 1.0


def test_auc_reversed_is_0():
    labels = torch.tensor([0.0, 0.0, 1.0, 1.0])
    assert roc_auc(labels, torch.tensor([0.9, 0.8, 0.2, 0.1])) == 0.0


def test_auc_all_ties_is_half():
    labels = torch.tensor([0.0, 1.0, 0.0, 1.0])
    assert roc_auc(labels, torch.tensor([0.5, 0.5, 0.5, 0.5])) == 0.5


# --- split ------------------------------------------------------------------


def test_split_holds_out_validation_edges_with_negatives(graph):
    torch.manual_seed(0)
    _, val_data = split_edges(graph, FAST)
    labels = val_data[graph.target].edge_label

    positives = int(labels.sum())
    negatives = int((labels == 0).sum())
    assert positives == 1  # 10% of the 10 "accessed" edges
    assert negatives == 2 * positives  # negative ratio 2, as in the paper


def test_validation_edges_are_hidden_from_training_messages(graph):
    torch.manual_seed(0)
    train_data, val_data = split_edges(graph, FAST)
    target = graph.target

    message_edges = set(map(tuple, train_data[target].edge_index.t().tolist()))
    val_labels = val_data[target].edge_label
    val_positives = val_data[target].edge_label_index[:, val_labels == 1]
    for edge in val_positives.t().tolist():
        assert tuple(edge) not in message_edges


# --- training ---------------------------------------------------------------


def test_training_reduces_the_loss(graph):
    result = train(graph, FAST)

    first_train_loss = result.history[0][1]
    best_train_loss = min(train_loss for _, train_loss, _ in result.history)
    assert best_train_loss < first_train_loss


def test_early_stopping_keeps_the_best_epoch(graph):
    result = train(graph, FAST)

    val_losses = [val_loss for _, _, val_loss in result.history]
    assert result.best_val_loss == min(val_losses)
    assert result.history[result.best_epoch - 1][2] == result.best_val_loss
    # training stopped at most `patience` epochs after the best one
    assert len(result.history) <= result.best_epoch + FAST.patience


def test_result_reports_auc_between_0_and_1(graph):
    result = train(graph, FAST)

    assert 0.0 <= result.val_auc <= 1.0


def test_same_seed_gives_same_result(graph):
    first = train(graph, FAST)
    second = train(graph, FAST)

    assert first.best_epoch == second.best_epoch
    assert first.best_val_loss == second.best_val_loss
    h1 = first.model.encode(graph.data)
    h2 = second.model.encode(graph.data)
    for node_type in graph.data.node_types:
        assert torch.equal(h1[node_type], h2[node_type])
