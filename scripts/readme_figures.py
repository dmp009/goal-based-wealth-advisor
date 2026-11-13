"""Regenerate the README images in docs/img/ from the engine (matplotlib re-plots of the app's
charts; no app screenshots).

Usage: python -m scripts.readme_figures  (or `make figures`)
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

from wealthadvisor.clients.models import list_sample_clients
from wealthadvisor.data.snapshot import load_snapshot
from wealthadvisor.proposal import build_proposal
from wealthadvisor.review.engine import build_review

OUT = Path("docs/img")
NAVY, BLUE, GREY, RED = "#1f3a5f", "#4a78b0", "#9aa5b1", "#c0392b"
METHOD = {"markowitz": "Markowitz", "black_litterman": "Black-Litterman", "hrp": "HRP"}
EUR = FuncFormatter(lambda x, _: f"€{x / 1000:,.0f}k")
plt.rcParams.update(
    {
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titleweight": "bold",
        "axes.titlesize": 11,
        "figure.dpi": 110,
    }
)


def _save(fig, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    fig.tight_layout()
    fig.savefig(path, metadata={"Software": None})
    plt.close(fig)
    return path


def fan_chart(bp, label: str) -> Path:
    q = bp.goal.paths_quantiles
    years = [m / 12 for m in q.index]
    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.fill_between(years, q["p10"], q["p90"], color=BLUE, alpha=0.25, label="10th to 90th pct.")
    ax.plot(years, q["p50"], color=NAVY, lw=2, label="Median")
    ax.axhline(bp.bucket.target_nominal, color=RED, ls="--", lw=1.2, label="Target (nominal)")
    ax.yaxis.set_major_formatter(EUR)
    ax.set_xlabel("Years from today")
    ax.set_title(
        f"{label}: projected value before tax (10,000 paths)\n"
        f"probability of reaching the target after tax: {bp.goal.probability * 100:.1f}%",
        loc="left",
    )
    ax.legend(frameon=False, loc="upper left")
    return _save(fig, "fan_chart_c2_retirement.png")


def method_comparison(bp, label: str) -> Path:
    methods = list(bp.methods)
    metrics = (
        ("Expected return", "expected_return", NAVY),
        ("Volatility", "volatility", BLUE),
        ("Max drawdown (historical)", "max_drawdown", GREY),
    )
    fig, ax = plt.subplots(figsize=(7.5, 4))
    width = 0.26
    for i, (name, attr, color) in enumerate(metrics):
        xs = [k + (i - 1) * width for k in range(len(methods))]
        vals = [abs(getattr(bp.methods[m], attr)) * 100 for m in methods]
        bars = ax.bar(xs, vals, width, color=color, label=name)
        ax.bar_label(bars, fmt="%.1f", fontsize=8, padding=2)
    ax.set_xticks(range(len(methods)))
    ax.set_xticklabels([METHOD[m] + (" (chosen)" if m == bp.chosen else "") for m in methods])
    ax.set_ylabel("% (risky ETF sleeve)")
    ax.set_title(f"{label}: three optimisers, one risk model", loc="left")
    ax.legend(frameon=False, ncols=3, loc="upper center", bbox_to_anchor=(0.5, -0.1))
    return _save(fig, "method_comparison_c2_retirement.png")


def drift_bars(review, label: str) -> Path:
    d = review.drift
    band = review.drift_band * 100
    classes = [str(c) for c in d.index]
    fig, ax = plt.subplots(figsize=(7.5, 4))
    width = 0.38
    for i, c in enumerate(classes):
        t = float(d.loc[c, "target"]) * 100
        ax.add_patch(
            plt.Rectangle((i - 0.45, max(t - band, 0)), 0.9, 2 * band, color=GREY, alpha=0.18, lw=0)
        )
    ax.bar([i - width / 2 for i in range(len(classes))], d["target"] * 100, width,
           color=GREY, label="Target")  # fmt: skip
    ax.bar([i + width / 2 for i in range(len(classes))], d["current"] * 100, width,
           color=NAVY, label="Current")  # fmt: skip
    for i, c in enumerate(classes):
        diff = float(d.loc[c, "diff"]) * 100
        if abs(diff) > band + 1e-9:
            ax.annotate(f"{diff:+.1f} pp", (i + width / 2, float(d.loc[c, "current"]) * 100),
                        ha="center", va="bottom", color=RED, fontsize=9, fontweight="bold",
                        xytext=(0, 3), textcoords="offset points")  # fmt: skip
    ax.set_xticks(range(len(classes)))
    ax.set_xticklabels([c.replace("_", " ") for c in classes], rotation=15)
    ax.set_ylabel("% of portfolio")
    ax.set_title(f"{label}: target vs current weights (shaded: ±{band:.0f} pp band)", loc="left")
    ax.legend(frameon=False)
    return _save(fig, "drift_c2.png")


def payoff_histogram(payoff, label: str) -> Path:
    fig, ax = plt.subplots(figsize=(7.5, 4))
    pay = payoff.payoff_multiple
    bins = [i / 40 for i in range(int(pay.max() * 40) + 2)]
    ax.hist(pay[pay < 1.0], bins=bins, color=RED, label="Capital loss (index below barrier)")
    ax.hist(
        pay[pay >= 1.0], bins=bins, color=NAVY, label="Capital returned, with coupons if called"
    )
    ax.set_yscale("log")
    ax.axvline(1.0, color=GREY, ls="--", lw=1)
    ax.set_xlabel("Payoff as a multiple of the invested capital (1.0 = capital back)")
    ax.set_ylabel("Simulated paths (log scale)")
    ax.set_title(
        f"{label}: autocall payoff distribution (10,000 index paths)\n"
        f"simulated probability of capital loss: {payoff.prob_capital_loss * 100:.1f}%",
        loc="left",
    )
    ax.legend(frameon=False, loc="upper left")
    return _save(fig, "structured_payoff_c3.png")


def main() -> None:
    con = load_snapshot()
    clients = {c.client_id: c for c in list_sample_clients()}
    c2, c3 = clients["c2"], clients["c3"]
    p2 = build_proposal(c2, con)
    retirement = next(bp for bp in p2.buckets if bp.bucket.goal_id == "retirement")
    paths = [
        fan_chart(retirement, "Moreau couple, retirement goal"),
        method_comparison(retirement, "Moreau couple, retirement bucket"),
        drift_bars(build_review(c2, con), "Moreau couple, annual review"),
    ]
    p3 = build_proposal(c3, con)
    if p3.structured.included and p3.structured.payoff is not None:
        paths.append(payoff_histogram(p3.structured.payoff, "Julien Deschamps"))
    for p in paths:
        print(f"Wrote {p}")


if __name__ == "__main__":
    main()
