"""New client workflow: situation, questionnaire, profile, wrappers, goals, structured, documents."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import json
from datetime import (
    date,
    timedelta,
)

import pandas as pd
import streamlit as st

from app.charts import (
    allocation_sunburst,
    fan_chart,
    method_comparison,
    payoff_histogram,
)
from app.common import (
    DOC_TABS,
    facts_json,
    footer,
    get_as_of,
    get_documents,
    get_etfs,
    get_proposal,
    get_sample_clients,
    setup,
)
from wealthadvisor.clients.models import Client, Goal
from wealthadvisor.config import load_questionnaire
from wealthadvisor.outputs.pdf import proposal_pdf
from wealthadvisor.proposal import METHODS

METHOD_LABEL = {"markowitz": "Markowitz", "black_litterman": "Black-Litterman", "hrp": "HRP"}
WRAPPER_LABEL = {"livret_a": "Livret A", "pea": "PEA", "av": "Life insurance (AV)", "cto": "CTO"}
BLANK = "Blank client"
NOT_GENERATED = (
    "Not generated yet — run `python -m wealthadvisor.pipeline ai --refresh` with an "
    "ANTHROPIC_API_KEY"
)

setup("New client")
st.title("New client")
Q = load_questionnaire()
QUESTIONS = {qid: q for s in Q["sections"].values() for qid, q in s["questions"].items()}


def _opt(key: str) -> str:
    return key.replace("_", " ")


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _eur(x: float) -> str:
    return f"{x:,.0f} EUR"


def answer_widgets(prefix: str, current: dict[str, str]) -> dict[str, str]:
    out = {}
    cols = st.columns(2)
    for i, (qid, q) in enumerate(QUESTIONS.items()):
        options = list(q["answers"])
        default = current.get(qid, options[len(options) // 2])
        out[qid] = cols[i % 2].selectbox(
            q["text"],
            options,
            index=options.index(default),
            format_func=_opt,
            key=f"{prefix}_{qid}",
        )
    return out


# --------------------------------------------------------------------------- client choice
samples = get_sample_clients()
choice = st.selectbox(
    "Client",
    [c.name for c in samples] + [BLANK],
    key="client_select",
    help="Four fictional sample clients, or enter a blank client.",
)

client: Client | None = None
if choice == BLANK:
    as_of = date.fromisoformat(get_as_of())
    add_second = st.checkbox("Add a second goal", key="blank_goal2")
    with st.form("blank_form"):
        st.subheader("Situation")
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Name", "New client")
        age = c2.number_input("Age", 18, 99, 40)
        household = c3.selectbox("Household", ["single", "couple"])
        c1, c2, c3, c4 = st.columns(4)
        income = c1.number_input("Annual income (EUR)", 0, 5_000_000, 50_000, step=1000)
        expenses = c2.number_input("Monthly expenses (EUR)", 0, 100_000, 2_000, step=100)
        liquid = c3.number_input("Liquid assets (EUR)", 0, 50_000_000, 30_000, step=1000)
        saving = c4.number_input("Monthly saving (EUR)", 0, 100_000, 500, step=50)
        st.subheader("Goals")
        goals_in = []
        for n in (1, 2):
            if n == 2 and not add_second:
                break
            g1, g2, g3, g4 = st.columns([3, 2, 2, 2])
            label = g1.text_input(f"Goal {n}", "Home purchase" if n == 1 else "Retirement top-up")
            target = g2.number_input(
                "Target (EUR, today's money)", 1000, 50_000_000, 60_000 if n == 1 else 150_000,
                step=1000, key=f"blank_t{n}",
            )  # fmt: skip
            gdate = g3.date_input(
                "Date", as_of + timedelta(days=365 * (5 if n == 1 else 15)), key=f"blank_d{n}"
            )
            prio = g4.selectbox(
                "Priority", ["essential", "aspirational"], index=n - 1, key=f"blank_p{n}"
            )
            goals_in.append((label, target, gdate, prio))
        st.subheader("Questionnaire")
        answers = answer_widgets("blank", {})
        submitted = st.form_submit_button("Build proposal", key="blank_submit", type="primary")
    if submitted:
        bad = [g[0] for g in goals_in if g[2] <= as_of]
        if bad:
            st.error(f"Goal date must be after the data date ({as_of}): {', '.join(bad)}")
        else:
            st.session_state["blank_client"] = Client(
                client_id="blank",
                name=name or "New client",
                age=int(age),
                household=household,
                annual_income=float(income),
                monthly_expenses=float(expenses),
                liquid_assets=float(liquid),
                debts=0.0,
                monthly_saving=float(saving),
                goals=[
                    Goal(
                        goal_id=f"goal{i}",
                        label=lb or f"Goal {i}",
                        label_fr=lb or f"Goal {i}",
                        target_today_eur=float(t),
                        date=d,
                        priority=p,
                    )
                    for i, (lb, t, d, p) in enumerate(goals_in, 1)
                ],
                answers=answers,
            )
    client = st.session_state.get("blank_client")
    if client is None:
        st.info("Fill in the form and press Build proposal.")
        footer()
        st.stop()
else:
    base = next(c for c in samples if c.name == choice)
    st.subheader("Situation")
    cols = st.columns(5)
    cols[0].metric("Age", base.age)
    cols[1].metric("Household", base.household)
    cols[2].metric("Annual income", _eur(base.annual_income))
    cols[3].metric("Liquid assets", _eur(base.liquid_assets))
    cols[4].metric("Monthly saving", _eur(base.monthly_saving))
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Goal": g.label,
                    "Target (today's EUR)": g.target_today_eur,
                    "Date": g.date.isoformat(),
                    "Priority": g.priority,
                }
                for g in base.goals
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    with st.expander("Questionnaire (editable answers)", expanded=False):
        answers = answer_widgets(f"q_{base.client_id}", base.answers)
    client = base.model_copy(update={"answers": answers})

# --------------------------------------------------------------------------- proposal
goal_ids = [g.goal_id for g in client.goals]
mkey = lambda gid: f"method_{client.client_id}_{gid}"
overrides = tuple(
    sorted((gid, st.session_state[mkey(gid)]) for gid in goal_ids if mkey(gid) in st.session_state)
)
try:
    p = get_proposal(client.model_dump_json(), overrides)
except ValueError as exc:
    st.error(f"Cannot build a proposal: {exc}")
    footer()
    st.stop()
facts_j = facts_json(p)
facts = json.loads(facts_j)
goals_by_id = {g.goal_id: g for g in client.goals}
etf_by_ticker = {e.ticker: e for e in get_etfs()}

st.header("Risk profile")
m1, m2 = st.columns(2)
m1.metric("Risk profile (1-7)", p.profile.profile)
m2.metric("Questionnaire score", f"{p.profile.raw_score:.2f}")
st.markdown("**Rules fired**")
for r in p.profile.rules_fired or ["No cap rule was binding."]:
    st.markdown(f"- {r}")
if p.profile.constraints:
    with st.expander("All applicable constraints"):
        for r in p.profile.constraints:
            st.markdown(f"- {r}")
for fam, s in p.suitability.items():
    for w in s.warnings:
        st.warning(f"Appropriateness ({fam}): {w}")
    if not s.included:
        st.error(f"Appropriateness ({fam}): not offered. " + " ".join(s.reasons))

st.header("Wrapper plan")
st.caption(
    f"Emergency fund target {_eur(p.emergency.target)}, funded {_eur(p.emergency.funded)}."
    + (f" Shortfall {_eur(p.emergency.shortfall)}." if p.emergency.shortfall > 0 else "")
)
for r in p.emergency.rules:
    st.caption(r)
rows = []
for w, prods in p.totals.items():
    for prod, v in prods.items():
        e = etf_by_ticker.get(prod)
        rows.append(
            {
                "Wrapper": WRAPPER_LABEL.get(w, w),
                "Product": e.name
                if e
                else prod.replace("_", " ").replace("structured:", "structured "),
                "Amount (EUR)": round(v),
            }
        )
left, right = st.columns([3, 2])
left.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
right.plotly_chart(allocation_sunburst(p), width="stretch")

st.header("Goals")
for bp in p.buckets:
    b = bp.bucket
    g = goals_by_id.get(b.goal_id)
    st.subheader(f"{g.label if g else b.goal_id}  ({g.priority if g else ''})")
    cols = st.columns(5)
    cols[0].metric("Target (nominal)", _eur(b.target_nominal))
    cols[1].metric("Probability of reaching it", f"{bp.goal.probability * 100:.0f}%")
    cols[2].metric("Expected return (bucket)", _pct(bp.expected_return))
    cols[3].metric("Volatility (bucket)", _pct(bp.volatility))
    cols[4].metric("Median outcome (after tax)", _eur(bp.goal.p50))
    if bp.shortfall_flag:
        st.warning(
            "Goal at risk: probability below 50%. Consider more saving, a later date or a "
            "lower target."
        )
    for r in b.rules:
        st.caption(r)
    sel = st.selectbox(
        "Allocation method",
        list(METHODS),
        index=list(METHODS).index(bp.chosen),
        format_func=METHOD_LABEL.get,
        key=mkey(b.goal_id),
    )
    cmp_rows = [
        {
            "Method": METHOD_LABEL[m] + (" (selected)" if m == bp.chosen else ""),
            "Expected return": _pct(r.expected_return),
            "Volatility": _pct(r.volatility),
            "Max drawdown": _pct(r.max_drawdown),
            "Notes": " ".join(r.notes),
        }
        for m, r in bp.methods.items()
    ]
    st.caption("Method comparison for the risky ETF sleeve")
    t1, t2 = st.columns([3, 2])
    t1.dataframe(pd.DataFrame(cmp_rows), width="stretch", hide_index=True)
    t2.plotly_chart(method_comparison(bp), width="stretch", key=f"cmp_{b.goal_id}")
    st.plotly_chart(fan_chart(bp.goal, b.target_nominal), width="stretch", key=f"fan_{b.goal_id}")
    held = {t for prods in bp.holdings_eur.values() for t in prods}
    unv = [
        f"{etf_by_ticker[t].name} ({', '.join(etf_by_ticker[t].unverified_fields)})"
        for t in sorted(held)
        if t in etf_by_ticker and etf_by_ticker[t].unverified_fields
    ]
    if unv:
        st.caption("Unverified ETF fields (see Product universe): " + "; ".join(unv) + ".")

st.header("Structured product")
s = p.structured
for w in p.structured_warnings:
    st.warning(w)
if s.included:
    st.success(
        f"Included: {facts['structured']['product_name']}, {_eur(s.amount)} in {s.wrapper.upper()}"
    )
    if s.payoff is not None:
        st.write(s.payoff.describe)
        st.metric("Probability of capital loss", _pct(s.payoff.prob_capital_loss))
        st.plotly_chart(payoff_histogram(s.payoff), width="stretch", key="payoff")
else:
    st.info("No structured product is proposed.")
    for r in s.reasons:
        st.markdown(f"- {r}")

st.header("AI documents")
docs = get_documents(facts_j)
tabs = st.tabs([label for label, _, _ in DOC_TABS])
for tab, (_, dt, lang) in zip(tabs, DOC_TABS, strict=True):
    with tab:
        d = docs[(dt, lang)]
        if d is None:
            st.info(NOT_GENERATED)
        elif not d.verified:
            st.error(
                "This document failed numeric verification and is not shown: " + "; ".join(d.errors)
            )
        else:
            st.subheader(d.title)
            st.markdown(d.body)

st.header("PDF export")
lang = st.radio("Language", ["en", "fr"], horizontal=True, key="pdf_lang")
letters = {lg: docs[("proposal_client", lg)] for lg in ("en", "fr")}
st.download_button(
    "Download proposal (PDF)",
    data=proposal_pdf(p, facts, letters, lang),
    file_name=f"proposal_{client.client_id}_{lang}.pdf",
    mime="application/pdf",
)
footer()
