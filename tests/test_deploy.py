"""Deployment checks: pinned requirements and a complete AI document cache."""

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "ai_cache"


def _name(req: str) -> str:
    return re.split(r"[<>=!~\[ ]", req, maxsplit=1)[0].lower().replace("_", "-")


def test_requirements_pin_every_runtime_dependency_exactly():
    lines = [
        ln.strip()
        for ln in (ROOT / "requirements.txt").read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    assert lines[-1] == "."  # the package itself, installed after its pinned dependencies
    pins = lines[:-1]
    assert pins and all(re.fullmatch(r"[A-Za-z0-9_.\-]+==[0-9][\w.]*", p) for p in pins), pins
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    assert {_name(d) for d in deps} <= {_name(p) for p in pins}


def test_runtime_python_version_is_declared():
    assert re.fullmatch(r"python-3\.\d+", (ROOT / "runtime.txt").read_text().strip())


@pytest.mark.skipif(
    not CACHE.is_dir() or not any(CACHE.glob("*.json")),
    reason="AI cache not generated (run `python -m wealthadvisor.pipeline ai --refresh`)",
)
def test_ai_cache_has_every_sample_document():
    from wealthadvisor.ai.documents import cache_key
    from wealthadvisor.clients.models import list_sample_clients
    from wealthadvisor.config import load_settings
    from wealthadvisor.data.snapshot import load_snapshot
    from wealthadvisor.proposal import build_proposal, proposal_facts
    from wealthadvisor.review.engine import build_review, review_facts

    version = load_settings().prompt_version
    con = load_snapshot()
    missing = []
    for c in list_sample_clients():
        jobs = [(proposal_facts(build_proposal(c, con)), ("proposal_advisor", "proposal_client"))]
        if c.original_proposal:
            jobs.append((review_facts(build_review(c, con)), ("review_advisor", "review_client")))
        for facts, doc_types in jobs:
            for dt in doc_types:
                for lang in ("en", "fr"):
                    if not (CACHE / f"{cache_key(facts, dt, lang, version)}.json").exists():
                        missing.append(f"{c.client_id} {dt}/{lang}")
    assert not missing, missing
