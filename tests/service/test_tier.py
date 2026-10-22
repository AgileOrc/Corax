import pytest
from risk import RiskModel
from tier import TierLimits, assess

ANY_USERS = TierLimits(max_user_share=1.0)


def test_small_scope_with_normal_risk_is_small(model_dir):
    scope = assess([("u1", "r1")], RiskModel.load(model_dir), ANY_USERS)

    assert (scope.users, scope.pairs, scope.tier, scope.reasons) == (1, 1, "small", ())
    assert scope.mean_risk == pytest.approx(0.018, abs=0.001)


def test_high_mean_risk_makes_it_large(model_dir):
    scope = assess([("u1", "r2")], RiskModel.load(model_dir), ANY_USERS)

    assert scope.tier == "large"
    assert scope.reasons == ("mean risk 0.98 > 0.5",)


def test_too_large_a_share_of_users_or_too_many_pairs_makes_it_large(model_dir):
    limits = TierLimits(max_user_share=0.5, max_pairs=2, max_mean_risk=1.0)

    scope = assess([("u1", "r1"), ("u2", "r1"), ("u2", "r2")], RiskModel.load(model_dir), limits)

    assert (scope.users, scope.user_share, scope.tier) == (2, 1.0, "large")
    assert scope.reasons == ("2 users (100% of 2) > 50%", "3 pairs > 2")


def test_user_share_at_the_limit_is_still_small(model_dir):
    limits = TierLimits(max_user_share=0.5, max_pairs=10, max_mean_risk=1.0)

    scope = assess([("u1", "r1"), ("u1", "r2")], RiskModel.load(model_dir), limits)

    assert (scope.user_share, scope.tier) == (0.5, "small")


def test_default_user_share_is_forty_percent():
    assert TierLimits().max_user_share == 0.4


@pytest.mark.parametrize(
    "limits",
    [{"max_user_share": 1.5}, {"max_user_share": -0.1}, {"max_pairs": -1}, {"max_mean_risk": 2.0}],
)
def test_limits_out_of_range_are_rejected(limits):
    with pytest.raises(ValueError):
        TierLimits(**limits)


def test_pairs_without_embeddings_are_left_out_of_the_mean(model_dir):
    scope = assess([("u1", "r1"), ("nobody", "r1")], RiskModel.load(model_dir))

    assert scope.mean_risk == pytest.approx(0.018, abs=0.001)
    assert scope.pairs == 2


def test_no_known_pair_has_no_mean_risk(model_dir):
    scope = assess([("nobody", "nothing")], RiskModel.load(model_dir), ANY_USERS)

    assert scope.mean_risk is None
    assert scope.tier == "small"
