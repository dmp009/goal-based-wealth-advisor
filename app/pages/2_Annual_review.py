"""Annual review: performance, drift, re-profiling, goals before/now, rebalancing, documents."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json

import pandas as pd
import streamlit as st

from app.charts import drift_bars, goal_probability_change
from app.common import (
    REVIEW_DOC_TABS,
    footer,
    get_etfs,
    get_review,
    get_review_documents,
    get_sample_clients,
    setup,
)
from wealthadvisor.config import load_questionnaire
from wealthadvisor.outputs.pdf import review_pdf
from wealthadvisor.review.engine import review_facts

WRAPPER_LABEL = {"livret_a": "Livret A", "pea": "PEA", "av": "Life insurance (AV)", "cto": "CTO"}
NOT_GENERATED = (
    "Not generated yet — run `python -m wealthadvisor.pipeline ai --refresh` with an "
    "ANTHROPIC_API_KEY"
)

setup("Annual review")
st.title("Annual review")
Q = load_questionnaire()
QUESTIONS = {qid: q for s in Q["sections"].values() for qid, q in s["questions"].items()}


def _opt(key: str) -> str:
    return key.replace("_", " ")


def _eur(x: float) -> str:
    return f"{x:,.0f} EUR"


samples = [c for c in get_sample_clients() if c.original_proposal]
if not samples:
    st.info("No client with an existing portfolio — use New client.")
    footer()
    st.stop()
choice = st.selectbox(
    "Client",
    [c.name for c in samples],
    key="review_client",
    help="Only clients with an existing portfolio (original proposal) can be reviewed.",
)
client = next(c for c in samples if c.name == choice)

# --------------------------------------------------------------------------- re-profile form
st.header("Re-profile")
st.caption("Edit the questionnaire answers and press Update to re-score the client today.")
with st.form(f"reprofile_{client.client_id}"):
    cols = st.columns(2)
    new_answers = {}
    for i, (qid, q) in enumerate(QUESTIONS.items()):
        options = list(q["answers"])
        default = client.answers.get(qid, options[len(options) // 2])
        new_answers[qid] = cols[i % 2].selectbox(
            q["text"], options, index=options.index(default), format_func=_opt,
            key=f"rq_{client.client_id}_{qid}",
        )  # fmt: skip
    st.form_submit_button("Update profile", key="reprofile_submit")

edited = tuple(sorted((k, v) for k, v in new_answers.items() if v != client.answers.get(k)))
r = get_review(client.model_dump_json(), tuple(sorted(new_answers.items())))
facts_j = json.dumps(review_facts(r), sort_keys=True)
facts = json.loads(facts_j)

m1, m2 = st.columns(2)
m1.metric("Profile at proposal date (1-7)", r.profile_before)
m2.metric("Profile now (1-7)", r.profile_now.profile)
if r.profile_changed:
    st.warning(
        f"Profile changed: {r.profile_before} at the proposal date, {r.profile_now.profile} now."
        + (" Based on edited answers." if edited else "")
    )
else:
    st.success("Profile unchanged.")
for rule in r.profile_now.rules_fired:
    st.caption(rule)

# --------------------------------------------------------------------------- performance
st.header("Performance")
st.caption(f"Since the proposal date ({r.proposal_date}), data as of {r.as_of}.")
rows = []
for k in [k for k in r.performance if k != "total"] + ["total"]:
    v = r.performance[k]
    rows.append(
        {
            "Scope": "Total" if k == "total" else WRAPPER_LABEL.get(k, k),
            "TWR (%)": round(v["twr"] * 100, 1),
            "Gain (EUR)": round(v["gain_eur"]),
            "Contributed (EUR)": round(v["contributed_eur"]),
            "Value (EUR)": round(v["value_eur"]),
        }
    )
tot = r.performance["total"]
a, b = st.columns(2)
a.metric("Total TWR", f"{tot['twr'] * 100:.1f}%")
b.metric("Total gain", _eur(tot["gain_eur"]))
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

# --------------------------------------------------------------------------- drift
st.header("Drift")
d = r.drift
left, right = st.columns([2, 3])
left.dataframe(
    pd.DataFrame(
        {
            "Asset class": [str(i).replace("_", " ") for i in d.index],
            "Target (%)": (d["target"] * 100).round(1).values,
            "Current (%)": (d["current"] * 100).round(1).values,
            "Difference (pp)": (d["diff"] * 100).round(1).values,
        }
    ),
    width="stretch", hide_index=True,
)  # fmt: skip
right.plotly_chart(drift_bars(d, r.drift_band), width="stretch")

# --------------------------------------------------------------------------- goals
st.header("Goals: before vs now")
labels = {g.goal_id: g.label for g in client.goals}
st.dataframe(
    pd.DataFrame(
        [
            {
                "Goal": labels.get(gb.goal_id, gb.goal_id),
                "Probability before (%)": round(gb.probability * 100, 1),
                "Probability now (%)": round(gn.probability * 100, 1),
                "Median now (EUR)": round(gn.p50),
            }
            for gb, gn in zip(r.goals_before, r.goals_now, strict=True)
        ]
    ),
    width="stretch", hide_index=True,
)  # fmt: skip
st.plotly_chart(goal_probability_change(r, client.goals), width="stretch")

# --------------------------------------------------------------------------- trades
st.header("Rebalancing trades")
if not r.trades:
    st.info(
        f"No rebalancing needed: all asset classes are within ±{r.drift_band * 100:g} pp of target."
    )
else:
    names = {e.ticker: e.name for e in get_etfs()}
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Wrapper": WRAPPER_LABEL.get(t.wrapper, t.wrapper),
                    "Product": names.get(t.product, t.product.replace("_", " ")),
                    "Action": t.action,
                    "Amount (EUR)": round(t.amount_eur),
                    "Taxable": "yes" if t.taxable else "no",
                    "Est. tax (EUR)": round(t.est_tax_eur),
                }
                for t in r.trades
            ]
        ),
        width="stretch", hide_index=True,
    )  # fmt: skip

# --------------------------------------------------------------------------- documents
st.header("AI documents")
docs = get_review_documents(facts_j)
tabs = st.tabs([label for label, _, _ in REVIEW_DOC_TABS])
for tab, (_, dt, lang) in zip(tabs, REVIEW_DOC_TABS, strict=True):
    with tab:
        doc = docs[(dt, lang)]
        if doc is None:
            st.info(NOT_GENERATED)
        elif not doc.verified:
            st.error(
                "This document failed numeric verification and is not shown: "
                + "; ".join(doc.errors)
            )
        else:
            st.subheader(doc.title)
            st.markdown(doc.body)

st.header("PDF export")
lang = st.radio("Language", ["en", "fr"], horizontal=True, key="review_pdf_lang")
letters = {lg: docs[("review_client", lg)] for lg in ("en", "fr")}
st.download_button(
    "Download review (PDF)",
    data=review_pdf(r, facts, letters, lang),
    file_name=f"review_{client.client_id}_{lang}.pdf",
    mime="application/pdf",
)
footer()
