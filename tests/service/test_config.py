import pytest
from config import Settings


def test_tier_limits_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("AUTO_APPLY_MAX_USER_SHARE", "0.5")
    monkeypatch.setenv("AUTO_APPLY_MAX_PAIRS", "200")
    monkeypatch.setenv("AUTO_APPLY_MAX_MEAN_RISK", "0.3")

    limits = Settings.from_env().tier_limits

    assert (limits.max_user_share, limits.max_pairs, limits.max_mean_risk) == (0.5, 200, 0.3)


def test_tier_limits_default_without_environment(monkeypatch):
    for name in ("AUTO_APPLY_MAX_USER_SHARE", "AUTO_APPLY_MAX_PAIRS", "AUTO_APPLY_MAX_MEAN_RISK"):
        monkeypatch.delenv(name, raising=False)

    limits = Settings.from_env().tier_limits

    assert (limits.max_user_share, limits.max_pairs, limits.max_mean_risk) == (0.4, 50, 0.5)


def test_a_share_written_as_a_percentage_is_rejected(monkeypatch):
    monkeypatch.setenv("AUTO_APPLY_MAX_USER_SHARE", "40")

    with pytest.raises(ValueError, match="between 0 and 1"):
        Settings.from_env()
