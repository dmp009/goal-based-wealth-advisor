"""ETF universe, structured-product templates and capital-market assumptions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd
import streamlit as st

from app.common import footer, get_etfs, setup
from wealthadvisor.config import load_cma_meta, load_structured

setup("Product universe")
st.title("Product universe")
st.markdown(
    "ETFs the optimisers may use. Fields listed as *unverified* could not be confirmed against a "
    "primary source (issuer factsheet or KID) and should be checked before any real use."
)

etfs = get_etfs()
rows = [
    {
        "Ticker": e.ticker,
        "ISIN": e.isin or "n/a",
        "Name": e.name,
        "Asset class": e.asset_class,
        "PEA eligible": {True: "yes", False: "no", None: "unknown"}[e.pea_eligible],
        "SRI (1-7)": e.sri if e.sri is not None else "n/a",
        "TER": f"{e.ter * 100:.2f}%" if e.ter is not None else "n/a",
        "Proxy for": e.proxy or "",
        "Unverified fields": ", ".join(e.unverified_fields) or "none",
        "Sources": " ; ".join(e.sources),
    }
    for e in etfs
]
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
n_unv = sum(1 for e in etfs if e.unverified_fields)
st.warning(f"{n_unv} of {len(etfs)} ETFs have at least one unverified field.")

st.subheader("Structured products")
tpl = load_structured().get("templates", {})
st.dataframe(
    pd.DataFrame([{"Id": k, **{kk: str(vv) for kk, vv in v.items()}} for k, v in tpl.items()]),
    width="stretch",
    hide_index=True,
)
st.caption("Generic templates on the Euro Stoxx 50, simulated; not real issuer products.")

st.subheader("Capital-market assumptions")
meta = load_cma_meta()
st.write(
    f"Source: {meta.get('source')} | as of: {meta.get('as_of')} | "
    f"unverified: {meta.get('unverified')}"
)
footer()
