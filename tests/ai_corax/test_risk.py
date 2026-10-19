import json
import math

import pytest
from risk import RiskModel, _sigmoid


def test_loads_only_the_target_user_and_object_types(model_dir, threshold):
    model = RiskModel.load(model_dir)

    assert set(model.users) == {"u1", "u2"}
    assert set(model.objects) == {"r1", "r2"}
    assert model.threshold == threshold


def test_known_pair_scores_low_risk(model_dir):
    result = RiskModel.load(model_dir).risk("u1", "r1")

    assert result.risk == pytest.approx(1 - 1 / (1 + math.exp(-4)))
    assert result.high_risk is False


def test_unknown_pair_scores_high_risk(model_dir):
    result = RiskModel.load(model_dir).risk("u1", "r2")

    assert result.risk == pytest.approx(1 - 1 / (1 + math.exp(4)))
    assert result.high_risk is True


@pytest.mark.parametrize(
    ("user", "obj", "reason"),
    [
        ("nobody", "r1", "unknown user"),
        ("u1", "nothing", "unknown object"),
        ("u1", "d1", "unknown object"),  # a department is not an object of the target relation
    ],
)
def test_missing_embedding_gives_no_score_and_never_denies(model_dir, user, obj, reason):
    result = RiskModel.load(model_dir).risk(user, obj)

    assert result.risk is None
    assert result.high_risk is False
    assert result.reason == reason


def test_threshold_override_wins_over_metadata(model_dir):
    model = RiskModel.load(model_dir, threshold=0.99)

    assert model.threshold == 0.99
    assert model.risk("u1", "r2").high_risk is False  # risk ≈ 0.982 is below 0.99


def test_old_export_without_threshold_is_rejected(model_dir):
    path = model_dir / "metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    del metadata["risk_threshold"]
    path.write_text(json.dumps(metadata), encoding="utf-8")

    with pytest.raises(ValueError, match="risk_threshold"):
        RiskModel.load(model_dir)


def test_sigmoid_does_not_overflow():
    assert _sigmoid(1000.0) == 1.0
    assert _sigmoid(-1000.0) == 0.0
    assert _sigmoid(0.0) == 0.5
