"""Method, stack and limitations."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from app.common import footer, setup

setup("About")
st.title("About")
st.markdown(
    """
**What it is.** A portfolio project that mirrors how a French bank advisor builds a goal-based
proposal. It is educational and is not investment advice.

**Method**
- *Profile*: a MiFID-style questionnaire gives a score from 1 to 7; cap rules (short horizon, low
  loss capacity, no ETF knowledge) can lower it, and each rule that fires is shown.
- *Buckets and wrappers*: one bucket per goal, risk level capped by horizon; an emergency fund
  first; Livret A, PEA, assurance-vie and CTO filled by simple, documented rules.
- *Portfolio*: Markowitz, Black-Litterman and HRP on a Ledoit-Wolf covariance, with
  capital-market assumptions as expected returns. The advisor can switch method per goal.
- *Goals*: Monte Carlo of each bucket with monthly contributions, inflation-adjusted target and
  French tax at the goal date; the probability shown is after tax.
- *Structured products*: generic autocall / capital-protected note on the Euro Stoxx 50, simulated,
  included only when the client's knowledge and profile allow it.
- *AI documents*: an LLM drafts the advisor summary and client letter (EN and FR) from the
  engine's facts only; a fail-closed checker rejects any number that is not in the facts. Unverified
  texts are never shown.

**Limitations**
- Simplified tax and wrapper rules; sample clients are fictional.
- Expected returns are assumptions, not forecasts; some ETF fields are unverified.
- Past volatility and normal returns understate tail risk.
"""
)
footer()
