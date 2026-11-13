import json
import types

import pytest

from wealthadvisor.ai import documents
from wealthadvisor.ai.client import AnthropicClient
from wealthadvisor.ai.documents import cache_key, generate
from wealthadvisor.config import load_settings

DISC = load_settings().disclaimer
FACTS = {
    "disclaimer": DISC,
    "client": {"name": "Claire", "age": 45},
    "goals": [{"label": "House", "probability_pct": 72.3, "target_nominal_eur": 38500}],
}


class FakeClient:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def write_document(self, prompt):
        self.prompts.append(prompt)
        return self.outputs.pop(0)


GOOD = {"title": "Letter", "body": "Dear Claire, 72.3 % chance for 38 500 EUR."}
BAD = {"title": "Letter", "body": "Dear Claire, 65 % chance."}


def test_generate_verified_and_disclaimer_appended(tmp_path):
    c = FakeClient(GOOD)
    d = generate("proposal_client", "en", FACTS, c, False, tmp_path)
    assert d.verified and d.errors == []
    assert d.body.endswith(DISC["en"])
    assert "<facts>" in c.prompts[0] and "38500" in c.prompts[0]
    assert d.doc_type == "proposal_client" and d.lang == "en" and d.title == "Letter"


def test_disclaimer_not_duplicated(tmp_path):
    out = {"title": "T", "body": GOOD["body"] + "\n\n" + DISC["en"]}
    d = generate("proposal_advisor", "en", FACTS, FakeClient(out), False, tmp_path)
    assert d.body.count(DISC["en"]) == 1


def test_retry_with_error_list_then_verified(tmp_path):
    c = FakeClient(BAD, GOOD)
    d = generate("proposal_client", "en", FACTS, c, False, tmp_path)
    assert d.verified
    assert len(c.prompts) == 2 and "65" in c.prompts[1]


def test_wrong_twice_unverified_and_not_cached(tmp_path):
    c = FakeClient(BAD, BAD)
    d = generate("proposal_client", "en", FACTS, c, False, tmp_path)
    assert not d.verified and d.errors
    assert list(tmp_path.glob("*.json")) == []


def test_cache_hit_and_refresh(tmp_path):
    generate("proposal_client", "en", FACTS, FakeClient(GOOD), False, tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 1
    c = FakeClient()
    d = generate("proposal_client", "en", FACTS, c, False, tmp_path)
    assert d.verified and c.prompts == []
    c2 = FakeClient({"title": "New", "body": GOOD["body"]})
    d2 = generate("proposal_client", "en", FACTS, c2, True, tmp_path)
    assert d2.title == "New" and len(c2.prompts) == 1


def test_miss_without_client_returns_none(tmp_path, caplog):
    assert generate("proposal_client", "en", FACTS, None, False, tmp_path) is None
    assert "no cached" in caplog.text.lower()


def test_cache_key_changes_with_facts_lang_type():
    k = cache_key(FACTS, "proposal_client", "en")
    other = json.loads(json.dumps(FACTS))
    other["goals"][0]["probability_pct"] = 72.4
    assert cache_key(other, "proposal_client", "en") != k
    assert cache_key(FACTS, "proposal_client", "fr") != k
    assert cache_key(FACTS, "proposal_advisor", "en") != k
    assert cache_key(FACTS, "proposal_client", "en") == k


def test_prompt_content_fr_client(tmp_path):
    c = FakeClient({"title": "T", "body": "Chère Claire, 72,3 %."})
    generate("proposal_client", "fr", FACTS, c, False, tmp_path)
    p = c.prompts[0]
    assert "vouvoiement" in p.lower() and DISC["fr"] in p


def test_unknown_doc_type(tmp_path):
    with pytest.raises(ValueError):
        generate("nope", "en", FACTS, FakeClient(GOOD), False, tmp_path)


def _resp(stop_reason, content):
    return types.SimpleNamespace(stop_reason=stop_reason, content=content)


def _anthropic_with(resp, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    c = AnthropicClient()
    calls = {}

    def create(**kw):
        calls.update(kw)
        return resp

    c._client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    return c, calls


def test_anthropic_client_forces_tool(monkeypatch):
    block = types.SimpleNamespace(type="tool_use", input={"title": "T", "body": "B"})
    c, calls = _anthropic_with(_resp("tool_use", [block]), monkeypatch)
    assert c.write_document("p") == {"title": "T", "body": "B"}
    assert calls["tool_choice"] == {"type": "tool", "name": "write_document"}
    assert calls["tools"][0]["name"] == "write_document"


def test_anthropic_client_max_tokens_raises(monkeypatch):
    c, _ = _anthropic_with(_resp("max_tokens", []), monkeypatch)
    with pytest.raises(RuntimeError, match="max_tokens"):
        c.write_document("p")


def test_anthropic_client_needs_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicClient()


def test_module_exports():
    assert documents.DOC_TYPES == (
        "proposal_advisor",
        "proposal_client",
        "review_advisor",
        "review_client",
    )
