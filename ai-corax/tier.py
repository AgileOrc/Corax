import random
from collections.abc import Sequence
from dataclasses import dataclass

from risk import RiskModel

Pair = tuple[str, str]


@dataclass(frozen=True)
class TierLimits:
    max_users: int = 5
    max_pairs: int = 50
    max_mean_risk: float = 0.5


@dataclass(frozen=True)
class Scope:
    users: int
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
    sample = opened if len(opened) <= risk_sample else random.Random(0).sample(opened, risk_sample)
    risks = [r.risk for r in (model.risk(u, o) for u, o in sample) if r.risk is not None]
    mean_risk = sum(risks) / len(risks) if risks else None

    reasons = []
    if users > limits.max_users:
        reasons.append(f"{users} users > {limits.max_users}")
    if len(opened) > limits.max_pairs:
        reasons.append(f"{len(opened)} pairs > {limits.max_pairs}")
    if mean_risk is not None and mean_risk > limits.max_mean_risk:
        reasons.append(f"mean risk {mean_risk:.2f} > {limits.max_mean_risk}")
    return Scope(
        users=users,
        pairs=len(opened),
        mean_risk=mean_risk,
        tier="large" if reasons else "small",
        reasons=tuple(reasons),
    )
