import io
import json

import pytest
from docapp import opa as opa_module
from docapp.opa import Opa, OpaError


def test_asks_opa_for_the_allowed_objects(monkeypatch):
    sent = {}

    def urlopen(request, timeout):
        sent["url"], sent["body"] = request.full_url, json.loads(request.data)
        return io.BytesIO(json.dumps({"result": ["document_D001"]}).encode())

    monkeypatch.setattr(opa_module.urllib.request, "urlopen", urlopen)

    allowed = Opa("http://opa:8181/").allowed_objects("employee_E001", "read", "document", ["document_D001", "document_D002"])

    assert allowed == {"document_D001"}
    assert sent["url"] == "http://opa:8181/v1/data/corax/authz/allowed_objects"
    assert sent["body"] == {"input": {"user": "employee_E001", "action": "read", "resource_type": "document",
                                      "objects": ["document_D001", "document_D002"]}}  # fmt: skip


def test_no_result_means_nothing_is_allowed(monkeypatch):
    monkeypatch.setattr(opa_module.urllib.request, "urlopen", lambda request, timeout: io.BytesIO(b"{}"))

    assert Opa("http://opa:8181").allowed_objects("u", "read", "document", ["d"]) == set()


def test_an_unreachable_opa_raises(monkeypatch):
    def urlopen(request, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(opa_module.urllib.request, "urlopen", urlopen)

    with pytest.raises(OpaError, match="not reachable"):
        Opa("http://opa:8181").allowed_objects("u", "read", "document", ["d"])
