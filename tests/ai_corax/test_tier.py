import pytest
from risk import RiskModel
from tier import TierLimits, assess


def test_small_scope_with_normal_risk_is_small(model_dir):
    scope = assess([("u1", "r1")], RiskModel.load(model_dir))

    assert (scope.users, scope.pairs, scope.tier, scope.reasons) == (1, 1, "small", ())
    assert scope.mean_risk == pytest.approx(0.018, abs=0.001)


def test_high_mean_risk_makes_it_large(model_dir):
    scope = assess([("u1", "r2")], RiskModel.load(model_dir))

    assert scope.tier == "large"
    assert scope.reasons == ("mean risk 0.98 > 0.5",)


def test_too_many_users_or_pairs_makes_it_large(model_dir):
    limits = TierLimits(max_users=1, max_pairs=2, max_mean_risk=1.0)

    scope = assess([("u1", "r1"), ("u2", "r1"), ("u2", "r2")], RiskModel.load(model_dir), limits)

    assert scope.tier == "large"
    assert scope.reasons == ("2 users > 1", "3 pairs > 2")


def test_pairs_without_embeddings_are_left_out_of_the_mean(model_dir):
    scope = assess([("u1", "r1"), ("nobody", "r1")], RiskModel.load(model_dir))

    assert scope.mean_risk == pytest.approx(0.018, abs=0.001)
    assert scope.pairs == 2


def test_no_known_pair_has_no_mean_risk(model_dir):
    scope = assess([("nobody", "nothing")], RiskModel.load(model_dir))

    assert scope.mean_risk is None
    assert scope.tier == "small"
