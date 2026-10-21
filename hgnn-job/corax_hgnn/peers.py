import random
from collections import defaultdict

import torch
from torch import Tensor

from corax_hgnn.graph import Graph


class PeerIndex:
    def __init__(self, graph: Graph, target_edges: Tensor):
        # Build the index from the graph's group edges and the given (user, object) edges.
        # Only `target_edges` count as "owned", so callers decide what is visible
        data, target = graph.data, graph.target

        # user -> groups, group -> users. A group is (edge type, attribute node index).
        self.groups_of: dict[int, list] = defaultdict(list)
        self.members: dict[tuple, list[int]] = defaultdict(list)
        for edge_type in data.edge_types:
            if edge_type[0] != target[0] or edge_type == target or edge_type[1].startswith("rev_"):
                continue
            sources, destinations = data[edge_type].edge_index.tolist()
            for user, node in zip(sources, destinations, strict=True):
                group = (edge_type, node)
                self.groups_of[user].append(group)
                self.members[group].append(user)

        # user -> objects, the set of known pairs, and how many members of a group own an object
        self.owned: dict[int, list[int]] = defaultdict(list)
        self.known: set[tuple[int, int]] = set()
        self.owners_in_group: dict[tuple, int] = defaultdict(int)
        for user, obj in zip(*target_edges.tolist(), strict=True):
            if (user, obj) in self.known:
                continue
            self.owned[user].append(obj)
            self.known.add((user, obj))
            for group in self.groups_of[user]:
                self.owners_in_group[(group, obj)] += 1

    def hard_negatives(
        self, users: list[int], per_user: int, rng: random.Random, max_tries: int = 20
    ) -> Tensor:
        # For each user, `per_user` objects owned by a random peer but not by the user
        sources, destinations = [], []
        for user in users:
            groups = self.groups_of.get(user)
            if not groups:
                continue
            for _ in range(per_user):
                for _ in range(max_tries):
                    peer = rng.choice(self.members[rng.choice(groups)])
                    if peer == user or not self.owned.get(peer):
                        continue
                    obj = rng.choice(self.owned[peer])
                    if (user, obj) not in self.known:
                        sources.append(user)
                        destinations.append(obj)
                        break
        return torch.tensor([sources, destinations], dtype=torch.long).reshape(2, -1)

    def coverage(self, pairs: Tensor) -> Tensor:
        # For each (user, object): the highest share of peers in any of the user's groups who own the object. The user is never counted as their own peer
        values = []
        for user, obj in pairs.t().tolist():
            self_owns = 1 if (user, obj) in self.known else 0
            best = 0.0
            for group in self.groups_of.get(user, []):
                peers = len(self.members[group]) - 1
                if peers > 0:
                    best = max(
                        best, (self.owners_in_group.get((group, obj), 0) - self_owns) / peers
                    )
            values.append(best)
        return torch.tensor(values, dtype=torch.float)
