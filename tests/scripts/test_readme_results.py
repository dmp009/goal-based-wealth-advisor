import pytest

from scripts.readme_results import (
    END,
    START,
    render_block,
    render_clients_table,
    render_reviews_table,
    replace_block,
)

FACTS = {
    "as_of": "2026-10-31",
    "client": {"name": "Test Client", "age": 45, "household": "couple"},
    "profile": {"risk_profile_count": 5},
    "goals": [
        {
            "label": "Retirement",
            "target_today_eur": 250000,
            "target_nominal_eur": 300000,
            "goal_year": 2040,
            "probability_pct": 87.4,
        }
    ],
    "structured": {
        "included": True,
        "product_name": "Autocall on the Euro Stoxx 50",
        "amount_eur": 30000,
        "wrapper": "av",
        "prob_capital_loss_pct": 4.6,
    },
}
EXCLUDED = {**FACTS, "structured": {"included": False, "reasons": ["No knowledge declared."]}}
REVIEW = {
    "client": {"name": "Test Client"},
    "proposal_date": "2025-04-30",
    "as_of": "2026-10-31",
    "review_period_months_count": 18,
    "performance": {"total": {"twr_pct": 12.3, "gain_eur": 25300}},
    "trades": [{"amount_eur": 500}, {"amount_eur": 500}],
    "trade_totals": {"sells_eur": 500, "buys_eur": 500, "est_tax_eur": 0},
    "goals": [{"label": "Retirement", "probability_before_pct": 61.3, "probability_now_pct": 86.0}],
}


def test_clients_table_row():
    table = render_clients_table([FACTS, EXCLUDED])
    lines = table.splitlines()
    assert len(lines) == 4
    assert lines[2].startswith("| Test Client | 45, couple | 5 / 7 |")
    assert "Retirement: €250,000, 2040, **87.4%**" in lines[2]
    assert "**Included**: Autocall on the Euro Stoxx 50, €30,000 in assurance-vie" in lines[2]
    assert "**Excluded**: No knowledge declared." in lines[3]


def test_reviews_table_row():
    row = render_reviews_table([REVIEW]).splitlines()[2]
    assert "2025-04-30 to 2026-10-31 (18 months)" in row
    assert "| 12.3% | €25,300 |" in row
    assert "2 (€500 sold, €0 est. tax)" in row
    assert "Retirement: 61.3% → 86.0%" in row


def test_review_without_trades():
    row = render_reviews_table([{**REVIEW, "trades": []}]).splitlines()[2]
    assert "0 (all classes inside the band)" in row


def test_replace_block_is_idempotent():
    readme = f"intro\n{START}\nSTALE-TABLE\n{END}\noutro\n"
    block = render_block([FACTS], [REVIEW], "2026-10-31")
    once = replace_block(readme, block)
    assert "STALE-TABLE" not in once and "last price date 2026-10-31" in once
    assert replace_block(once, block) == once
    assert once.startswith("intro\n") and once.endswith("outro\n")


def test_replace_block_requires_markers():
    with pytest.raises(ValueError):
        replace_block("no markers", "x")
