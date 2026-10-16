"""Self-supervised link prediction training, following Yin et al. 2024.

1. Split the target edges (e.g. "accessed") into training and validation edges (0.9 / 0.1).
2. Each epoch: encode the graph, score positive edges and random negative pairs (2 per positive),
   and minimise binary cross-entropy.
3. After each epoch, compute the validation loss. Stop when it has not improved for `patience`
   epochs, and keep the weights from the best epoch.

The paper trains in mini-batches; we train full-batch because the graphs are small
(see docs/ai-design.md, section 3.2).
"""

import copy
import logging
import random
from dataclasses import dataclass, field

import numpy as np
import torch
import torch.nn.functional as F
import torch_geometric.transforms as T
from torch import Tensor
from torch_geometric.data import HeteroData
from torch_geometric.utils import negative_sampling

from corax_hgnn.graph import Graph
from corax_hgnn.model import HGNN, link_logits

log = logging.getLogger(__name__)


@dataclass
class TrainConfig:
    hidden: int = 64
    learning_rate: float = 0.001
    max_epochs: int = 1000
    patience: int = 10
    val_ratio: float = 0.1
    negative_ratio: float = 2.0
    seed: int = 0


@dataclass
class TrainResult:
    model: HGNN
    best_epoch: int
    best_val_loss: float
    val_auc: float
    # one entry per epoch: (epoch, train loss, validation loss)
    history: list[tuple[int, float, float]] = field(default_factory=list)


def split_edges(graph: Graph, config: TrainConfig) -> tuple[HeteroData, HeteroData]:
    """Split the target edges into training and validation sets.

    Part of the training edges are only used as labels, not for message passing,
    so the model cannot simply "see" the edge it has to predict.
    """
    transform = T.RandomLinkSplit(
        num_val=config.val_ratio,
        num_test=0.0,
        disjoint_train_ratio=0.3,
        neg_sampling_ratio=config.negative_ratio,
        add_negative_train_samples=False,  # sampled fresh every epoch instead
        edge_types=graph.target,
        rev_edge_types=graph.target_reverse,
    )
    train_data, val_data, _ = transform(graph.data)
    return train_data, val_data


def sample_training_pairs(
    data: HeteroData, target, negative_ratio: float
) -> tuple[Tensor, Tensor]:
    """Positive training edges plus fresh random negative pairs, with their 0/1 labels."""
    positives = data[target].edge_label_index
    known = torch.cat([data[target].edge_index, positives], dim=1)
    negatives = negative_sampling(
        edge_index=known,
        num_nodes=(data[target[0]].num_nodes, data[target[2]].num_nodes),
        num_neg_samples=int(positives.size(1) * negative_ratio),
    )
    pairs = torch.cat([positives, negatives], dim=1)
    labels = torch.cat([torch.ones(positives.size(1)), torch.zeros(negatives.size(1))])
    return pairs, labels


def loss_and_scores(model: HGNN, data: HeteroData, target, pairs, labels):
    h = model.encode(data)
    logits = link_logits(h[target[0]], h[target[2]], pairs)
    return F.binary_cross_entropy_with_logits(logits, labels), logits


def roc_auc(labels: Tensor, scores: Tensor) -> float:
    """Area under the ROC curve: the chance that a random positive scores above a random negative.

    Computed from ranks (Mann-Whitney U); tied scores get their average rank.
    """
    sorted_scores, order = scores.sort()
    _, inverse, counts = torch.unique_consecutive(
        sorted_scores, return_inverse=True, return_counts=True
    )
    last = counts.cumsum(0).double()
    first = last - counts + 1
    ranks = torch.empty_like(scores, dtype=torch.double)
    ranks[order] = ((first + last) / 2)[inverse]

    n_pos = labels.sum().item()
    n_neg = labels.numel() - n_pos
    rank_sum = ranks[labels == 1].sum().item()
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def train(graph: Graph, config: TrainConfig | None = None) -> TrainResult:
    config = config or TrainConfig()
    # PyG's negative sampling uses Python's and NumPy's random generators, not only torch's.
    random.seed(config.seed)
    np.random.seed(config.seed)
    torch.manual_seed(config.seed)

    train_data, val_data = split_edges(graph, config)
    target = graph.target
    val_pairs = val_data[target].edge_label_index
    val_labels = val_data[target].edge_label.float()

    model = HGNN(graph.data, hidden=config.hidden)
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)

    best_state, best_epoch, best_val_loss = None, 0, float("inf")
    history = []

    for epoch in range(1, config.max_epochs + 1):
        # Training step
        model.train()
        optimizer.zero_grad()
        pairs, labels = sample_training_pairs(train_data, target, config.negative_ratio)
        train_loss, _ = loss_and_scores(model, train_data, target, pairs, labels)
        train_loss.backward()
        optimizer.step()

        # Validation step
        model.eval()
        with torch.no_grad():
            val_loss, _ = loss_and_scores(model, val_data, target, val_pairs, val_labels)
        history.append((epoch, train_loss.item(), val_loss.item()))

        if val_loss.item() < best_val_loss:
            best_state = copy.deepcopy(model.state_dict())
            best_epoch, best_val_loss = epoch, val_loss.item()
        elif epoch - best_epoch >= config.patience:
            log.info("early stop at epoch %d (best epoch %d)", epoch, best_epoch)
            break

        if epoch % 10 == 0:
            log.info("epoch %d  train %.4f  val %.4f", epoch, train_loss.item(), val_loss.item())

    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        _, val_scores = loss_and_scores(model, val_data, target, val_pairs, val_labels)

    return TrainResult(
        model=model,
        best_epoch=best_epoch,
        best_val_loss=best_val_loss,
        val_auc=roc_auc(val_labels, val_scores),
        history=history,
    )
