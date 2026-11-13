"""Pure plotly figure builders for the Streamlit app (no Streamlit imports)."""

from __future__ import annotations

import plotly.graph_objects as go

from wealthadvisor.config import load_etfs

NAVY = "#1f3a5f"
BLUE = "#4a78b0"
ACCENT = "#c0392b"
GREY = "#9aa5b1"
_METHOD = {"markowitz": "Markowitz", "black_litterman": "Black-Litterman", "hrp": "HRP"}
_WRAPPER = {"livret_a": "Livret A", "pea": "PEA", "av": "Life insurance (AV)", "cto": "CTO"}
_LAYOUT = {"margin": {"l": 10, "r": 10, "t": 40, "b": 10}, "template": "plotly_white"}


def fan_chart(goal, target: float | None = None) -> go.Figure:
    """P10-P90 band and median of the bucket value path (EUR, pre-tax), target as a line."""
    q = goal.paths_quantiles
    years = [m / 12 for m in q.index]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=years, y=q["p90"], line={"width": 0}, name="P90", showlegend=False))
    fig.add_trace(
        go.Scatter(
            x=years, y=q["p10"], line={"width": 0}, fill="tonexty",
            fillcolor="rgba(74,120,176,0.25)", name="P10 to P90",
        )
    )  # fmt: skip
    fig.add_trace(go.Scatter(x=years, y=q["p50"], line={"color": NAVY, "width": 2}, name="Median"))
    if target is not None:
        fig.add_hline(
            y=target, line={"color": ACCENT, "dash": "dash"},
            annotation_text="Target (nominal)", annotation_position="top left",
        )  # fmt: skip
    fig.update_layout(
        xaxis_title="Years", yaxis_title="EUR", title="Projected value (before final tax)",
        hovermode="x unified", **_LAYOUT,
    )  # fmt: skip
    return fig


def allocation_sunburst(proposal) -> go.Figure:
    """Wrapper -> product amounts across the whole proposal (incl. the emergency fund)."""
    names = {e.ticker: e.name for e in load_etfs()}
    names.update({"livret_a": "Livret A", "fonds_euros": "Fonds en euros"})
    ids, labels, parents, values = [], [], [], []
    for w, prods in proposal.totals.items():
        ids.append(w)
        labels.append(_WRAPPER.get(w, w))
        parents.append("")
        values.append(sum(prods.values()))
        for prod, v in prods.items():
            ids.append(f"{w}/{prod}")
            labels.append(
                names.get(prod, prod.replace("structured:", "Structured ") if prod else prod)
            )
            parents.append(w)
            values.append(v)
    fig = go.Figure(
        go.Sunburst(
            ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
            hovertemplate="%{label}<br>%{value:,.0f} EUR<extra></extra>",
        )
    )  # fmt: skip
    fig.update_layout(title="Allocation by wrapper and product", **_LAYOUT)
    return fig


def method_comparison(bucket_proposal) -> go.Figure:
    """Expected return, volatility and max drawdown of the risky sleeve, per method."""
    methods = list(bucket_proposal.methods)
    labels = [_METHOD.get(m, m) for m in methods]
    fig = go.Figure()
    for name, attr, color in (
        ("Expected return", "expected_return", NAVY),
        ("Volatility", "volatility", BLUE),
        ("Max drawdown", "max_drawdown", GREY),
    ):
        fig.add_trace(
            go.Bar(
                x=labels, y=[abs(getattr(bucket_proposal.methods[m], attr)) * 100 for m in methods],
                name=name, marker_color=color,
            )
        )  # fmt: skip
    fig.update_layout(
        barmode="group", yaxis_title="% (risky sleeve)", title="Method comparison", **_LAYOUT
    )
    return fig


def payoff_histogram(payoff) -> go.Figure:
    """Distribution of the product's payoff multiple at exit (1.0 = capital back)."""
    fig = go.Figure(
        go.Histogram(x=list(payoff.payoff_multiple), nbinsx=40, marker_color=NAVY, name="Payoff")
    )
    fig.add_vline(x=1.0, line={"color": ACCENT, "dash": "dash"}, annotation_text="Capital")
    fig.update_layout(
        xaxis_title="Payoff multiple of invested capital", yaxis_title="Simulated paths",
        title="Structured product payoff distribution", showlegend=False, **_LAYOUT,
    )  # fmt: skip
    return fig
