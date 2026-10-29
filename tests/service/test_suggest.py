import numpy as np
from risk import RiskModel
from similar import SimilarityIndex
from suggest import score, suggested


def model():
    users = {"u1": np.array([1.0, 0.0]), "u2": np.array([0.9, 0.1]), "u3": np.array([-1.0, 0.0])}
    objects = {"o1": np.array([5.0, 0.0]), "o2": np.array([-5.0, 0.0])}
    return RiskModel(users, objects, threshold=0.5, metadata={"target_edge_type": ["user", "accessed", "object"]})


ACCESS = {("u2", "o1")}


def can_reach(user, obj):
    return (user, obj) in ACCESS


def test_scores_objects_by_peers_with_access_then_risk():
    m = model()

    found = score(m, SimilarityIndex(m), can_reach, "u1", ["o2", "o1"], peers=2)

    assert [(s.object, s.peers_with_access, s.peers) for s in found] == [("o1", 1, 2), ("o2", 0, 2)]
    assert found[0].risk < 0.01 < 0.99 < found[1].risk


def test_access_the_user_has_is_never_scored():
    m = model()

    assert score(m, SimilarityIndex(m), can_reach, "u2", ["o1"], peers=2) == []


def test_only_low_risk_pairs_most_peers_have_are_suggested():
    m = model()
    found = score(m, SimilarityIndex(m), can_reach, "u1", ["o1", "o2"], peers=2)

    assert [s.object for s in suggested(found, threshold=0.5, min_share=0.5)] == ["o1"]
    assert suggested(found, threshold=0.5, min_share=0.6) == []
    assert suggested(found, threshold=0.001, min_share=0.5) == []
