import os
from dataclasses import dataclass, field
from pathlib import Path

from tier import TierLimits


@dataclass(frozen=True)
class Settings:
    model_dir: Path
    risk_threshold: float | None = None
    opa_path: str = "opa"
    policy_dir: Path | None = None
    generated_dir: Path = Path("policies/generated")
    appeals_dir: Path = Path("appeals")
    corax_config: Path | None = None
    object_identity: bool = False
    candidates: int = 8
    tier_limits: TierLimits = field(default_factory=TierLimits)

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        threshold, policy_dir = env("AI_RISK_THRESHOLD"), env("POLICY_DIR")
        defaults = TierLimits()
        return cls(
            model_dir=Path(env("CORAX_MODEL_DIR", "output/hgnn")),
            risk_threshold=float(threshold) if threshold else None,
            opa_path=env("OPA_PATH", "opa"),
            policy_dir=Path(policy_dir) if policy_dir else None,
            generated_dir=Path(env("GENERATED_DIR", "policies/generated")),
            appeals_dir=Path(env("APPEALS_DIR", "appeals")),
            corax_config=Path(env("CORAX_CONFIG")) if env("CORAX_CONFIG") else None,
            object_identity=env("OBJECT_IDENTITY", "false").lower() in {"1", "true", "yes"},
            candidates=int(env("APPEAL_CANDIDATES", 8)),
            tier_limits=TierLimits(
                max_user_share=float(env("AUTO_APPLY_MAX_USER_SHARE", defaults.max_user_share)),
                max_pairs=int(env("AUTO_APPLY_MAX_PAIRS", defaults.max_pairs)),
                max_mean_risk=float(env("AUTO_APPLY_MAX_MEAN_RISK", defaults.max_mean_risk)),
            ),
        )
