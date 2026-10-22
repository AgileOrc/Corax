# Prints a JWT for the demo, signed with the HS256 secret of a Corax config (data.json).
# Only for demos and tests: production uses a "cert" (public key) and tokens come from the real identity provider.
#
# python scripts/make_token.py --sub lecturer_P1_0
# python scripts/make_token.py --sub admin_rina --config deploy/demo/data.json --minutes 120

import argparse
import json
import time
from pathlib import Path

import jwt

ROOT = Path(__file__).resolve().parents[1]


def make_token(config_file: Path, sub: str, minutes: int) -> str:
    settings = json.loads(config_file.read_text(encoding="utf-8"))["corax"]["config"]["jwt"]
    if "secret" not in settings:
        raise ValueError(f"{config_file} has no jwt.secret; tokens for a cert come from the identity provider")
    now = int(time.time())
    claims = {"sub": sub, "iat": now, "exp": now + minutes * 60}
    for key in ("iss", "aud"):
        if key in settings:
            claims[key] = settings[key]
    return jwt.encode(claims, settings["secret"], algorithm="HS256")


def main() -> None:
    parser = argparse.ArgumentParser(description="Print a demo JWT signed with the HS256 secret of a Corax config.")
    parser.add_argument("--sub", required=True, help="user id, e.g. lecturer_P1_0 or admin_rina")
    parser.add_argument("--config", type=Path, default=ROOT / "deploy" / "demo" / "data.json")
    parser.add_argument("--minutes", type=int, default=60, help="lifetime of the token (default 60)")
    args = parser.parse_args()
    try:
        print(make_token(args.config, args.sub, args.minutes))
    except (OSError, KeyError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
