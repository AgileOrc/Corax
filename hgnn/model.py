import torch
from torch import Tensor, nn
from torch_geometric.data import HeteroData
from torch_geometric.nn import SAGEConv, to_hetero


class Encoder(nn.Module):
    # building model
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
        # making the 1st vector (h0)
        self.node_embeddings = nn.ModuleDict(
            {
                node_type: nn.Embedding(data[node_type].num_nodes, hidden)
                for node_type in data.node_types
            }
        )
        # SAGEConv layers. The SAGEConv usually for only 1 type edge graph, so to_hetero used to copying for every edge 
        self.encoder = to_hetero(Encoder(hidden, num_layers), metadata=data.metadata())

    # counting the embedding for every nodes
    def encode(self, data: HeteroData) -> dict[str, Tensor]:
        # Return the final vector h of every node, grouped by node type
        x = {
            node_type: self.node_embeddings[node_type](data[node_type].node_id)
            for node_type in data.node_types
        }
        return self.encoder(x, data.edge_index_dict)

# scoring every pair
def link_logits(h_src: Tensor, h_dst: Tensor, edge_label_index: Tensor) -> Tensor:
    # Dot product h_src · h_dst for each pair in edge_label_index (shape [2, num_pairs]).
    # The result is a logit: sigmoid(logit) is the probability that the link exists.
    return (h_src[edge_label_index[0]] * h_dst[edge_label_index[1]]).sum(dim=-1)

# converting logit into probability values (decimal)
def link_probability(h_src: Tensor, h_dst: Tensor, edge_label_index: Tensor) -> Tensor:
    return torch.sigmoid(link_logits(h_src, h_dst, edge_label_index))
