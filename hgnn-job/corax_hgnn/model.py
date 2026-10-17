# Heterogeneous GraphSAGE model
#     node id ──► learnable embedding ──► SAGEConv ──► ReLU ──► SAGEConv ──► h (one vector per node)
# The two SAGEConv layers are written for a homogeneous graph and converted with
# `to_hetero`, which creates one copy of each layer per edge type.
# Link prediction scores a (source, destination) pair with the dot product of their vectors.

import torch
from torch import Tensor, nn
from torch_geometric.data import HeteroData
from torch_geometric.nn import SAGEConv, to_hetero


class Encoder(nn.Module):
    # GraphSAGE for a homogeneous graph: SAGEConv layers with ReLU in between.
    # The paper uses 2 layers; 1 layer mixes less neighbour information (experiment E1).
    def __init__(self, hidden: int, num_layers: int = 2):
        super().__init__()
        self.convs = nn.ModuleList(SAGEConv(hidden, hidden) for _ in range(num_layers))

    def forward(self, x: Tensor, edge_index: Tensor) -> Tensor:
        for i, conv in enumerate(self.convs):
            x = conv(x, edge_index)
            if i < len(self.convs) - 1:
                x = x.relu()
        return x


class HGNN(nn.Module):
    def __init__(self, data: HeteroData, hidden: int = 64, num_layers: int = 2):
        super().__init__()
        # The input of each node is a learnable vector (no hand-made features), as in the paper.
        self.node_embeddings = nn.ModuleDict(
            {
                node_type: nn.Embedding(data[node_type].num_nodes, hidden)
                for node_type in data.node_types
            }
        )
        self.encoder = to_hetero(Encoder(hidden, num_layers), metadata=data.metadata())

    def encode(self, data: HeteroData) -> dict[str, Tensor]:
        # Return the final vector h of every node, grouped by node type
        x = {
            node_type: self.node_embeddings[node_type](data[node_type].node_id)
            for node_type in data.node_types
        }
        return self.encoder(x, data.edge_index_dict)


def link_logits(h_src: Tensor, h_dst: Tensor, edge_label_index: Tensor) -> Tensor:
    # Dot product h_src · h_dst for each pair in edge_label_index (shape [2, num_pairs]).
    # The result is a logit: sigmoid(logit) is the probability that the link exists.
    return (h_src[edge_label_index[0]] * h_dst[edge_label_index[1]]).sum(dim=-1)


def link_probability(h_src: Tensor, h_dst: Tensor, edge_label_index: Tensor) -> Tensor:
    return torch.sigmoid(link_logits(h_src, h_dst, edge_label_index))
