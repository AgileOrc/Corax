"""What the policy lets someone open, asked of OPA on the internal network (never through Envoy), so
the catalog lists only those documents and never shows the titles of the rest."""

import json
import urllib.error
import urllib.request


class OpaError(Exception):
    pass


class Opa:
    def __init__(self, url: str, timeout: float = 5):
        self.url = url.rstrip("/")
        self.timeout = timeout

    def allowed_objects(self, user: str, action: str, resource_type: str, objects: list[str]) -> set[str]:
        """The objects the policy allows user to reach with action: the application's rules, rules
        from appeals and exceptions (data.corax.authz.allowed_objects). The AI check still decides when
        one is opened. Raises OpaError when OPA does not answer, so the caller fails closed."""
        body = {"input": {"user": user, "action": action, "resource_type": resource_type, "objects": objects}}
        request = urllib.request.Request(
            f"{self.url}/v1/data/corax/authz/allowed_objects", json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )  # fmt: skip
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                answer = json.loads(response.read())
        except (OSError, ValueError) as error:
            raise OpaError(f"OPA is not reachable at {self.url}: {error}") from error
        return set(answer.get("result") or [])
