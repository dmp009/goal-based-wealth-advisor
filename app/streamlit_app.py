"""Goal-based wealth advisor: landing page."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from app.common import footer, get_as_of, setup

setup("Home")
st.title("Goal-based wealth advisor")
st.markdown(
    "A decision-support tool for a French bank wealth advisor. It turns a client's situation, "
    "goals and MiFID-style questionnaire into a documented investment proposal across French "
    "wrappers (Livret A, PEA, assurance-vie, CTO), with every number computed by a deterministic "
    "engine and every AI-written document checked against those numbers."
)

c1, c2 = st.columns(2)
with c1:
    st.subheader("1. New client")
    st.markdown(
        "- Capture the situation and the questionnaire answers\n"
        "- Deterministic risk profile and the rules that fired\n"
        "- One bucket per goal: wrapper plan, Markowitz / Black-Litterman / HRP comparison\n"
        "- Monte Carlo probability of reaching each goal, after tax\n"
        "- Structured product decision with its payoff distribution\n"
        "- Bilingual (EN/FR) advisor summary and client letter, PDF export"
    )
    st.page_link("pages/1_New_client.py", label="Open New client")
with c2:
    st.subheader("2. Annual review")
    st.markdown(
        "- Compare an existing proposal with the current market snapshot\n"
        "- Drift versus target weights and goal probability update\n"
        "- Suggested rebalancing, explained in plain language"
    )

st.info(
    "Sample clients are fictional. All market data comes from a committed snapshot, so the app "
    "is reproducible and needs no live connection."
)
st.caption(f"Data as of {get_as_of()}.")
footer()
