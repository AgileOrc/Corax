"""Passwords (PBKDF2 from the standard library) and the JWTs that Envoy, OPA and the service verify.

In the demo the app is the identity provider: it signs tokens with the HS256 secret of
demo/data.json, the settings OPA's io.jwt.decode_verify and the service check. A real deployment
gets its tokens from an identity provider (config "cert") and the app would not hold the secret.
"""

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

import jwt

SCHEME = "pbkdf2_sha256"


def hash_password(password: str, iterations: int, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{SCHEME}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, digest = stored.split("$")
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    except ValueError:
        return False
    return scheme == SCHEME and hmac.compare_digest(candidate.hex(), digest)


class TokenError(Exception):
    pass


class Tokens:
    """Issues and verifies the demo's JWTs with the settings of demo/data.json."""

    def __init__(self, corax_config: Path, minutes: int):
        config = json.loads(corax_config.read_text(encoding="utf-8"))["corax"]["config"]
        settings = config["jwt"]
        if "secret" not in settings:
            raise ValueError(f"{corax_config} has no jwt.secret: the demo app can only issue HS256 tokens")
        self.secret = settings["secret"]
        self.issuer = settings.get("iss")
        self.audience = settings.get("aud")
        self.minutes = minutes
        self.admins = frozenset(config.get("admin", {}).get("users", []))

    def issue(self, subject: str) -> tuple[str, int]:
        """A token for subject and its lifetime in seconds."""
        now = int(time.time())
        claims = {"sub": subject, "iat": now, "exp": now + self.minutes * 60}
        if self.issuer:
            claims["iss"] = self.issuer
        if self.audience:
            claims["aud"] = self.audience
        return jwt.encode(claims, self.secret, algorithm="HS256"), self.minutes * 60

    def subject(self, token: str) -> str:
        try:
            claims = jwt.decode(
                token, self.secret, algorithms=["HS256"], audience=self.audience, issuer=self.issuer,
                options={"require": ["exp", "sub"]},
            )  # fmt: skip
        except jwt.PyJWTError as error:
            raise TokenError(str(error)) from error
        return claims["sub"]
