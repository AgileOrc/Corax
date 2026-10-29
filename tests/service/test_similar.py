import json

import numpy as np
import pytest
from graph import GraphData
from risk import RiskModel
from similar import SimilarCase, SimilarityIndex, closest


def write_model(folder, users, objects, access):
    np.savez(
        folder / "embeddings.npz",
        lecturer=np.array(list(users.values()), dtype=np.float32),
        student=np.array(list(objects.values()), dtype=np.float32),
    )
    node_ids = {"lecturer": list(users), "student": list(objects)}
    (folder / "node_ids.json").write_text(json.dumps(node_ids), encoding="utf-8")
    metadata = {
        "target_edge_type": ["lecturer", "accessed", "student"],
        "risk_threshold": {"value": 0.9},
    }
    (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (folder / "graph.json").write_text("{}", encoding="utf-8")
    (folder / "access.json").write_text(json.dumps(access), encoding="utf-8")
    return folder


@pytest.fixture
def campus(tmp_path):
    users = {"budi": [1.0, 0.0], "sari": [0.8, 0.6], "andi": [0.0, 1.0]}
    objects = {"candra": [1.0, 0.0], "fajar": [0.6, 0.8], "dewi": [0.8, 0.6], "xavier": [0.0, 1.0]}
    access = {"budi": ["fajar"]}
    folder = write_model(tmp_path, users, objects, access)
    graph = GraphData.load(folder)
    return SimilarityIndex(RiskModel.load(folder)), graph


def pairs(cases):
    return [(c.user, c.object) for c in cases]


def test_similarity_is_the_mean_of_user_and_object_cosine(campus):
    index, graph = campus

    best = index.find("budi", "candra", k=1, has_access=graph.has_access, max_per_user=None)[0]

    assert (best.user, best.object) == ("budi", "dewi")
    assert best.user_similarity == pytest.approx(1.0)
    assert best.object_similarity == pytest.approx(0.8)
    assert best.similarity == pytest.approx(0.9)


def test_neighbours_are_ranked_by_similarity(campus):
    index, graph = campus

    cases = index.find("budi", "candra", k=3, has_access=graph.has_access, max_per_user=None)

    assert pairs(cases) == [("budi", "dewi"), ("sari", "candra"), ("sari", "dewi")]
    scores = [c.similarity for c in cases]
    assert scores == sorted(scores, reverse=True)


def test_appealed_pair_and_existing_access_are_skipped(campus):
    index, graph = campus

    found = pairs(
        index.find("budi", "candra", k=12, has_access=graph.has_access, max_per_user=None)
    )

    assert ("budi", "candra") not in found
    assert ("budi", "fajar") not in found
    assert len(found) == 3 * 4 - 2


def test_each_user_appears_at_most_max_per_user_times(campus):
    index, graph = campus

    cases = index.find("budi", "candra", k=10, has_access=graph.has_access, max_per_user=1)

    assert pairs(cases) == [("budi", "dewi"), ("sari", "candra"), ("andi", "candra")]


def test_default_limit_is_two_per_user(campus):
    index, graph = campus

    users = [c.user for c in index.find("budi", "candra", k=10, has_access=graph.has_access)]

    assert users.count("budi") == 2
    assert max(users.count(u) for u in set(users)) == 2


def test_unknown_user_or_object_is_rejected(campus):
    index, _ = campus

    with pytest.raises(ValueError, match="unknown user"):
        index.find("nobody", "candra")
    with pytest.raises(ValueError, match="unknown object"):
        index.find("budi", "nothing")


def test_graph_data_reads_access_history(campus):
    _, graph = campus

    assert graph.has_access("budi", "fajar")
    assert not graph.has_access("budi", "candra")
    assert not graph.has_access("nobody", "fajar")


def brute_force(users, objects, access, user, obj, k, max_per_user=None):
    def unit(v):
        v = np.asarray(v, dtype=np.float64)
        return v / np.linalg.norm(v)

    scored = []
    for u, hu in users.items():
        for o, ho in objects.items():
            if (u, o) == (user, obj) or o in access.get(u, []):
                continue
            score = (unit(hu) @ unit(users[user]) + unit(ho) @ unit(objects[obj])) / 2
            scored.append((score, u, o))
    scored.sort(key=lambda t: -t[0])
    picked, count = [], {}
    for score, u, o in scored:
        if max_per_user is not None and count.get(u, 0) >= max_per_user:
            continue
        count[u] = count.get(u, 0) + 1
        picked.append((score, u, o))
    return picked[:k]


@pytest.mark.parametrize("max_per_user", [None, 1, 3])
@pytest.mark.parametrize("seed", range(5))
def test_same_result_as_scoring_every_pair(tmp_path, seed, max_per_user):
    rng = np.random.default_rng(seed)
    users = {f"u{i}": rng.normal(size=8).tolist() for i in range(60)}
    objects = {f"o{i}": rng.normal(size=8).tolist() for i in range(80)}
    access = {u: [o for o in objects if rng.random() < 0.5] for u in users}
    folder = write_model(tmp_path, users, objects, access)
    index, graph = SimilarityIndex(RiskModel.load(folder)), GraphData.load(folder)

    found = index.find("u0", "o0", k=25, has_access=graph.has_access, max_per_user=max_per_user)
    expected = brute_force(users, objects, access, "u0", "o0", k=25, max_per_user=max_per_user)

    assert pairs(found) == [(u, o) for _, u, o in expected]
    assert [c.similarity for c in found] == pytest.approx([s for s, _, _ in expected])


def test_closest_keeps_the_cases_near_the_first_and_at_least_a_few():
    found = [SimilarCase("u", f"o{i}", s, s, s) for i, s in enumerate([0.98, 0.97, 0.96, 0.94, 0.90, 0.89])]

    assert [c.object for c in closest(found, 2, 0.03)] == ["o0", "o1", "o2"]
    assert len(closest(found, 5, 0.03)) == 5  # an unusual appeal still gets the minimum
    assert len(closest(found, 2, 0.5)) == 6 and closest([], 5, 0.03) == []
