"""Shared helpers for the Streamlit pages. Reads only committed files (snapshot, clients, AI cache,
config, data_quality_report.md); no network and no API key needed."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)  # engine config paths are relative to the repo root

import streamlit as st

from wealthadvisor.ai.documents import generate
from wealthadvisor.clients.models import Client, list_sample_clients
from wealthadvisor.config import load_etfs, load_settings
from wealthadvisor.data.snapshot import load_snapshot
from wealthadvisor.proposal import build_proposal, proposal_facts, snapshot_today
from wealthadvisor.review.engine import build_review

DOC_TABS = (
    ("Advisor EN", "proposal_advisor", "en"),
    ("Advisor FR", "proposal_advisor", "fr"),
    ("Client EN", "proposal_client", "en"),
    ("Client FR", "proposal_client", "fr"),
)
REVIEW_DOC_TABS = (
    ("Advisor EN", "review_advisor", "en"),
    ("Advisor FR", "review_advisor", "fr"),
    ("Client EN", "review_client", "en"),
    ("Client FR", "review_client", "fr"),
)


def setup(title: str) -> None:
    st.set_page_config(page_title=f"Wealth advisor - {title}", page_icon=None, layout="wide")


@st.cache_resource(show_spinner="Loading data snapshot...")
def get_con():
    return load_snapshot()


@st.cache_data
def get_as_of() -> str:
    return snapshot_today(get_con()).isoformat()


@st.cache_data
def get_settings():
    return load_settings()


@st.cache_data
def get_sample_clients() -> list[Client]:
    return list_sample_clients()


@st.cache_data
def get_etfs():
    return load_etfs()


@st.cache_resource(show_spinner="Building proposal...", max_entries=64)
def get_proposal(client_json: str, overrides: tuple[tuple[str, str], ...]):
    client = Client.model_validate(json.loads(client_json))
    return build_proposal(client, get_con().cursor(), dict(overrides) or None)


@st.cache_data(show_spinner=False, max_entries=64)
def get_documents(facts_json: str) -> dict:
    """Cached AI documents keyed by (doc_type, lang); None when not generated yet."""
    facts = json.loads(facts_json)
    return {(dt, lang): generate(dt, lang, facts, None) for _, dt, lang in DOC_TABS}


@st.cache_resource(show_spinner="Building annual review...", max_entries=32)
def get_review(client_json: str, answers: tuple[tuple[str, str], ...]):
    client = Client.model_validate(json.loads(client_json))
    return build_review(client, get_con().cursor(), new_answers=dict(answers) or None)


@st.cache_data(show_spinner=False, max_entries=64)
def get_review_documents(facts_json: str) -> dict:
    facts = json.loads(facts_json)
    return {(dt, lang): generate(dt, lang, facts, None) for _, dt, lang in REVIEW_DOC_TABS}


def facts_json(proposal) -> str:
    return json.dumps(proposal_facts(proposal), sort_keys=True)


def footer() -> None:
    s = get_settings()
    st.divider()
    st.caption(f"{s.disclaimer['en']} | {s.disclaimer['fr']}")
    st.caption(f"Market data as of {get_as_of()} (committed snapshot; no live data).")
