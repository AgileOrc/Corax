# Access a user does not have yet but probably should: the other side of the risk score. The model was
# trained to predict access (link prediction); here its low-risk predictions for pairs without access
# are shown to an admin, together with how many of the user's closest peers can reach the same object.
# Nothing is granted: an admin decides, through the appeal flow.
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import numpy as np
from risk import RiskModel
from similar import SimilarityIndex

# How many of the most similar users are compared, and the share of them that must have the access for
# a pair to be suggested. Both are design choices, not measured values.
PEERS = 10
MIN_PEER_SHARE = 0.5


@dataclass(frozen=True)
class Scored:
    user: str
    object: str
    risk: float
    peers_with_access: int
    peers: int


def score(
    model: RiskModel,
    index: SimilarityIndex,
    can_reach: Callable[[str, str], bool],
    user: str,
    objects: Iterable[str],
    peers: int = PEERS,
) -> list[Scored]:
    """For each object the user cannot reach yet: the model's risk, and how many of the user's closest
    peers (cosine of the user embeddings) can reach it. Most covered by peers first, then lowest risk."""
    row = index.user_row[user]
    similarity = index.users @ index.users[row]
    similarity[row] = -np.inf
    closest = [index.user_ids[i] for i in np.argsort(-similarity)[:peers]]
    found = []
    for obj in objects:
        if obj not in model.objects or can_reach(user, obj):
            continue
        risk = model.risk(user, obj).risk
        found.append(Scored(user, obj, risk, sum(can_reach(p, obj) for p in closest), len(closest)))
    return sorted(found, key=lambda s: (-s.peers_with_access, s.risk, s.object))


def suggested(scored: Iterable[Scored], threshold: float, min_share: float = MIN_PEER_SHARE) -> list[Scored]:
    """The pairs worth an admin's look: the risk check would let them through, and most peers have them."""
    return [s for s in scored if s.risk <= threshold and s.peers and s.peers_with_access / s.peers >= min_share]
