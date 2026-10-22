import json
import threading
from dataclasses import dataclass
from pathlib import Path

import jwt


class AuthError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class AdminConfig:
    key: str
    algorithms: tuple[str, ...]
    issuer: str | None
    audience: str | None
    admins: frozenset[str]


class AdminAuth:
    def __init__(self, config_file: Path | None):
        self.config_file = config_file
        self._loaded: tuple[int, AdminConfig] | None = None
        self._lock = threading.Lock()

    def authenticate(self, authorization: str | None) -> str:
        config = self._config()
        if not authorization or not authorization.startswith("Bearer "):
            raise AuthError(401, "missing bearer token")
        try:
            claims = jwt.decode(
                authorization[len("Bearer "):],
                config.key,
                algorithms=list(config.algorithms),
                issuer=config.issuer,
                audience=config.audience,
                options={"require": ["exp", "sub"]},
            )
        except jwt.PyJWTError as error:
            raise AuthError(401, f"invalid token: {error}") from error
        user = claims["sub"]
        if not isinstance(user, str):
            raise AuthError(401, "invalid token: sub must be a string")
        if user not in config.admins:
            raise AuthError(403, f"{user} is not an admin")
        return user

    def _config(self) -> AdminConfig:
        if self.config_file is None:
            raise AuthError(503, "admin authentication is not configured")
        try:
            version = self.config_file.stat().st_mtime_ns
        except OSError as error:
            raise AuthError(503, f"cannot read {self.config_file}: {error}") from error
        with self._lock:
            if self._loaded is None or self._loaded[0] != version:
                self._loaded = (version, _parse(self.config_file))
            return self._loaded[1]


def _parse(path: Path) -> AdminConfig:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))["corax"]["config"]
        settings = config["jwt"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise AuthError(503, f"{path} has no corax.config.jwt") from error

    if "secret" in settings:
        key, algorithms = settings["secret"], ("HS256",)
    elif "cert" in settings:
        key, algorithms = settings["cert"], ("RS256", "ES256")
    else:
        raise AuthError(503, f"{path}: corax.config.jwt needs a secret or a cert")

    admins = config.get("admin", {}).get("users", [])
    return AdminConfig(
        key=key,
        algorithms=algorithms,
        issuer=settings.get("iss"),
        audience=settings.get("aud"),
        admins=frozenset(user for user in admins if isinstance(user, str)),
    )
