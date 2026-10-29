import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database: Path  # SQLite file, created and seeded on the first start
    seed_dir: Path | None  # nodes.csv and edges.csv of scripts/prepare/make_enterprise.py
    corax_config: Path  # demo/data.json: the JWT settings and the admins
    corax_gateway: str = "http://envoy:8080"  # appeals go through the gateway, as the admin
    opa_url: str = "http://opa:8181"  # what someone may open, for the catalog (internal network only)
    demo_password: str = "corax-demo"  # every seeded account gets it
    password_iterations: int = 100_000
    token_minutes: int = 60

    @classmethod
    def from_env(cls) -> "Settings":
        seed_dir = os.environ.get("SEED_DIR")
        return cls(
            database=Path(os.environ.get("DATABASE", "docapp.db")),
            seed_dir=Path(seed_dir) if seed_dir else None,
            corax_config=Path(os.environ.get("CORAX_CONFIG", "data.json")),
            corax_gateway=os.environ.get("CORAX_GATEWAY", cls.corax_gateway),
            opa_url=os.environ.get("OPA_URL", cls.opa_url),
            demo_password=os.environ.get("DEMO_PASSWORD", cls.demo_password),
            password_iterations=int(os.environ.get("PASSWORD_ITERATIONS", cls.password_iterations)),
            token_minutes=int(os.environ.get("TOKEN_MINUTES", cls.token_minutes)),
        )
