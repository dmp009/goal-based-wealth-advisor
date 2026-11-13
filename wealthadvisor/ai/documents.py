"""Bilingual AI documents drafted strictly from engine facts, numerically verified, cached."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from wealthadvisor.ai.client import LLMClient
from wealthadvisor.ai.numbers import verify
from wealthadvisor.config import REPO_ROOT, load_settings

logger = logging.getLogger(__name__)

DocType = Literal["proposal_advisor", "proposal_client", "review_advisor", "review_client"]
DOC_TYPES = ("proposal_advisor", "proposal_client", "review_advisor", "review_client")
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "ai_cache"
PROMPT_DIR = Path(__file__).parent / "prompts"
_LANG_NAME = {"en": "English", "fr": "French"}
_KIND = {
    "advisor": "ADVISOR SUMMARY (internal, technical tone)",
    "client": "CLIENT LETTER (letter tone, addressed to the client)",
}


@dataclass
class Document:
    doc_type: str
    lang: str
    title: str
    body: str
    cache_key: str
    verified: bool
    errors: list[str] = field(default_factory=list)


def cache_key(facts: dict, doc_type: str, lang: str, prompt_version: str | None = None) -> str:
    version = prompt_version if prompt_version is not None else load_settings().prompt_version
    raw = json.dumps(facts, sort_keys=True) + version + doc_type + lang
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_prompt(doc_type: str, lang: str, facts: dict, prompt_version: str) -> str:
    family, audience = doc_type.split("_")
    template = (PROMPT_DIR / f"{family}_{prompt_version}.md").read_text(encoding="utf-8")
    disclaimer = load_settings().disclaimer[lang]
    return (
        template.replace("{{DOC_KIND}}", _KIND[audience])
        .replace("{{LANGUAGE}}", _LANG_NAME[lang])
        .replace("{{DISCLAIMER}}", disclaimer)
        .replace("{{FACTS}}", json.dumps(facts, ensure_ascii=False, sort_keys=True, indent=1))
    )


def _ensure_disclaimer(body: str, disclaimer: str) -> str:
    body = body.rstrip()
    if body.rstrip("*_ \n").endswith(disclaimer):
        return body
    return f"{body}\n\n{disclaimer}"


def _read(path: Path) -> Document | None:
    try:
        return Document(**json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        logger.warning("Unreadable cache entry %s; ignoring", path)
        return None


def generate(
    doc_type: str,
    lang: Literal["en", "fr"],
    facts: dict,
    client: LLMClient | None,
    refresh: bool = False,
    cache_dir: Path | str = DEFAULT_CACHE_DIR,
) -> Document | None:
    if doc_type not in DOC_TYPES:
        raise ValueError(f"unknown doc_type {doc_type!r}")
    settings = load_settings()
    key = cache_key(facts, doc_type, lang, settings.prompt_version)
    path = Path(cache_dir) / f"{key}.json"
    cached = _read(path) if path.exists() else None
    if cached is not None and (not refresh or client is None):
        return cached
    if client is None:
        logger.warning("No cached %s/%s document and no LLM client; skipping", doc_type, lang)
        return None

    prompt = build_prompt(doc_type, lang, facts, settings.prompt_version)
    disclaimers = list(settings.disclaimer.values())
    title, body, errors = "", "", []
    for attempt in range(2):
        text = prompt
        if attempt:
            text += (
                "\n\nYour previous draft contained numbers that do not match the facts:\n"
                + "\n".join(f"- {e}" for e in errors)
                + "\n\nRewrite the whole document using only numbers that appear in the facts."
            )
        out = client.write_document(text)
        title = out["title"]
        body = _ensure_disclaimer(out["body"], settings.disclaimer[lang])
        errors = verify(f"{title}\n{body}", lang, facts, disclaimers)
        if not errors:
            break
    doc = Document(doc_type, lang, title, body, key, not errors, errors)
    if doc.verified:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(doc), ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        logger.warning("%s/%s unverified after retry: %s", doc_type, lang, errors)
    return doc
