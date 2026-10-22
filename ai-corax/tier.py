import random
from collections.abc import Sequence
from dataclasses import dataclass

from risk import RiskModel

Pair = tuple[str, str]


@dataclass(frozen=True)
class TierLimits:
    max_user_share: float = 0.4
    max_pairs: int = 50
    max_mean_risk: float = 0.5

    def __post_init__(self):
        if not 0 <= self.max_user_share <= 1:
            raise ValueError(f"max_user_share must be between 0 and 1, got {self.max_user_share}")
        if self.max_pairs < 0:
            raise ValueError(f"max_pairs must not be negative, got {self.max_pairs}")
        if not 0 <= self.max_mean_risk <= 1:
            raise ValueError(f"max_mean_risk must be between 0 and 1, got {self.max_mean_risk}")


@dataclass(frozen=True)
class Scope:
    users: int
    user_share: float
    pairs: int
    mean_risk: float | None
    tier: str
    reasons: tuple[str, ...]


def assess(
    opened: Sequence[Pair],
    model: RiskModel,
    limits: TierLimits | None = None,
    risk_sample: int = 10_000,
) -> Scope:
    limits = limits or TierLimits()
    users = len({user for user, _ in opened})
    user_share = users / len(model.users) if model.users else 0.0
    sample = opened if len(opened) <= risk_sample else random.Random(0).sample(opened, risk_sample)
    risks = [r.risk for r in (model.risk(u, o) for u, o in sample) if r.risk is not None]
    mean_risk = sum(risks) / len(risks) if risks else None

    reasons = []
    if user_share > limits.max_user_share:
        reasons.append(f"{users} users ({user_share:.0%} of {len(model.users)}) > {limits.max_user_share:.0%}")
    if len(opened) > limits.max_pairs:
        reasons.append(f"{len(opened)} pairs > {limits.max_pairs}")
    if mean_risk is not None and mean_risk > limits.max_mean_risk:
        reasons.append(f"mean risk {mean_risk:.2f} > {limits.max_mean_risk}")
    return Scope(
        users=users,
        user_share=user_share,
        pairs=len(opened),
        mean_risk=mean_risk,
        tier="large" if reasons else "small",
        reasons=tuple(reasons),
    )
