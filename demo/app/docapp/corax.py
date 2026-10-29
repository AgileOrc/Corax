"""Corax's appeal API, called through the gateway with the token of the admin who handles the
request: Envoy and OPA check it (only config.admin.users pass), then the service checks it again.
The app has no Corax account of its own."""

import json
import urllib.error
import urllib.request


class Corax:
    def __init__(self, gateway: str, timeout: float = 60):
        self.gateway = gateway.rstrip("/")
        self.timeout = timeout

    def create_appeal(self, token: str, user: str, document: str, reason: str | None) -> tuple[int, dict]:
        """201 with the record (exception applied, candidate patterns), or an error such as 409 when
        the user can read the document already."""
        body = {"user": user, "object": document, "action": "read", "reason": reason}
        return self._call("POST", "/corax/appeals", token, body)

    def confirm(self, token: str, appeal_id: str, candidate: int | None, acknowledge_scope: bool) -> tuple[int, dict]:
        """200 with the record (rule_applied or exception_only); 409 with the scope when the rule is
        large and not acknowledged; 422 when the rule failed validation."""
        body = {"candidate": candidate, "acknowledge_scope": acknowledge_scope}
        return self._call("POST", f"/corax/appeals/{appeal_id}/confirm", token, body)

    def revoke(self, token: str, appeal_id: str, exception: bool) -> tuple[int, dict]:
        """200 with the record (the rule's file deleted, who and when recorded; with exception, the
        employee's own exception too); 409 when nothing of the appeal is still in effect."""
        return self._call("POST", f"/corax/appeals/{appeal_id}/revoke", token, {"exception": exception})

    def suggestions(self, token: str, limit: int) -> tuple[int, dict]:
        """200 with the access the model expects but nobody granted yet (a list), for an admin."""
        return self._call("GET", f"/corax/suggestions?limit={limit}", token, None)

    def rank(self, token: str, user: str, relation: str, node: str) -> tuple[int, dict]:
        """200 with the objects linked to node by relation that user cannot reach yet, most covered by
        the user's peers first, and a warning when no peer can reach any of them."""
        return self._call("POST", "/corax/rank", token, {"user": user, "relation": relation, "node": node})

    def _call(self, method: str, path: str, token: str, body: dict | None) -> tuple[int, dict]:
        request = urllib.request.Request(
            self.gateway + path, None if body is None else json.dumps(body).encode(), method=method,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )  # fmt: skip
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.status, _json(response.read())
        except urllib.error.HTTPError as error:
            return error.code, _json(error.read())
        except OSError as error:
            return 502, {"error": f"Corax is not reachable at {self.gateway}: {error}"}


def _json(data: bytes) -> dict:
    try:
        value = json.loads(data) if data else {}
    except ValueError:
        return {"error": data.decode(errors="replace")[:500]}
    return value if isinstance(value, dict) else {"items": value}
