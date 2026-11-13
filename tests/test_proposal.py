import json
from datetime import date

import pytest

from wealthadvisor.clients.models import list_sample_clients
from wealthadvisor.config import load_etfs, load_profiles, load_settings
from wealthadvisor.data.snapshot import load_snapshot
from wealthadvisor.proposal import build_proposal, proposal_facts, save_proposal

CLIENTS = {c.client_id: c for c in list_sample_clients()}
NUMERIC_SUFFIXES = ("_pct", "_eur", "_year", "_count")


@pytest.fixture(scope="module")
def con():
    return load_snapshot()


@pytest.fixture(scope="module")
def proposals(con):
    return {cid: build_proposal(c, con) for cid, c in CLIENTS.items()}


def _sum(holdings: dict) -> float:
    return sum(v for products in holdings.values() for v in products.values())


def test_as_of_is_snapshot_last_price_date(con, proposals):
    last = con.execute("SELECT max(date) FROM fact_prices").fetchone()[0]
    assert last == date(2026, 10, 31)
    assert all(p.as_of == last for p in proposals.values())


def test_every_client_builds_with_three_methods_and_default_choice(proposals):
    for cid, p in proposals.items():
        assert p.client_id == cid
        assert len(p.buckets) == len(CLIENTS[cid].goals)
        for bp in p.buckets:
            assert set(bp.methods) == {"markowitz", "black_litterman", "hrp"}
            expected = "hrp" if bp.bucket.risk <= 3 else "black_litterman"
            assert bp.chosen == expected
            assert bp.goal.goal_id == bp.bucket.goal_id
            assert 0.0 <= bp.goal.probability <= 1.0


def test_bucket_holdings_sum_to_funding(proposals):
    for p in proposals.values():
        for bp in p.buckets:
            assert _sum(bp.holdings_eur) == pytest.approx(bp.bucket.funding_now, abs=1.0)
            assert all(v >= 0 for prods in bp.holdings_eur.values() for v in prods.values())


def test_totals_plus_emergency_equal_liquid_assets(proposals):
    for cid, p in proposals.items():
        assert _sum(p.totals) == pytest.approx(CLIENTS[cid].liquid_assets, abs=1.0)
        assert p.totals["livret_a"]["livret_a"] >= p.emergency.funded - 1.0


def test_pea_holdings_only_pea_eligible(proposals):
    eligible = {e.ticker for e in load_etfs() if e.pea_eligible is True}
    seen_pea = False
    for p in proposals.values():
        for holdings in [p.totals, *(bp.holdings_eur for bp in p.buckets)]:
            for product in holdings.get("pea", {}):
                seen_pea = True
                assert product in eligible, product
    assert seen_pea, "at least one sample client should use the PEA"


def test_regulatory_caps_per_client(proposals):
    eligible = {e.ticker for e in load_etfs() if e.pea_eligible is True}
    for cid, p in proposals.items():
        assert sum(p.totals.get("pea", {}).values()) <= 150_000 + 1.0, cid
        assert sum(p.totals.get("livret_a", {}).values()) <= 22_950 + 1.0, cid
        assert set(p.totals.get("pea", {})) <= eligible, cid


def test_sample_goal_probabilities_realistic(proposals):
    for cid, p in proposals.items():
        for bp in p.buckets:
            assert 0.0 < bp.goal.probability <= 1.0, (cid, bp.bucket.goal_id)
    prob = {
        (cid, bp.bucket.goal_id): bp.goal.probability
        for cid, p in proposals.items()
        for bp in p.buckets
    }
    assert 0.60 <= prob[("c1", "flat_deposit")] <= 0.85
    assert 0.25 <= prob[("c3", "holiday_home")] <= 0.65


def test_shortfall_flag_and_horizon_months(proposals):
    from wealthadvisor.proposal import projected_value

    for p in proposals.values():
        f = proposal_facts(p)
        for g, bp in zip(f["goals"], p.buckets):
            b = bp.bucket
            assert "underfunded" not in g
            assert g["shortfall_flag"] is (g["probability_pct"] < 50)
            assert g["projected_value_eur"] == round(projected_value(b, bp.expected_return))
            assert g["horizon_months_count"] == max(1, round(b.horizon_years * 12))
            assert g["horizon_years_count"] == round(b.horizon_years)


def test_shortfall_flag_examples(proposals):
    flags = {
        (cid, g["goal_id"]): g["shortfall_flag"]
        for cid, p in proposals.items()
        for g in proposal_facts(p)["goals"]
    }
    assert flags[("c4", "grandchildren")] is True  # 40.8 %
    assert flags[("c1", "flat_deposit")] is False  # 69.6 %


def test_projected_value_hand_computed():
    from wealthadvisor.proposal import projected_value
    from wealthadvisor.wrappers.allocate import Bucket

    b = Bucket("g", 1.0, 3, 1000.0, 100.0, 0.0, {}, 0.4, [])
    rm = 1.12 ** (1 / 12) - 1
    expected = 1000 * 1.12 + 100 * ((1 + rm) ** 12 - 1) / rm
    assert projected_value(b, 0.12) == pytest.approx(expected)
    assert projected_value(b, 0.0) == pytest.approx(1000 + 1200)


def test_mc_tax_uses_realised_wrapper_amounts(con, monkeypatch):
    import wealthadvisor.proposal as mod

    seen = {}
    real = mod.simulate_bucket

    def spy(bucket, *a, **k):
        seen[bucket.goal_id] = dict(bucket.wrapper_split)
        return real(bucket, *a, **k)

    monkeypatch.setattr(mod, "simulate_bucket", spy)
    p = mod.build_proposal(CLIENTS["c4"], con)
    for bp in p.buckets:
        realised = {w: sum(v.values()) for w, v in bp.holdings_eur.items()}
        assert seen[bp.bucket.goal_id] == pytest.approx(realised)
    # c4 care_reserve: HRP holds less equity than the planned split, so less goes to the PEA.
    care = next(bp for bp in p.buckets if bp.bucket.goal_id == "care_reserve")
    assert seen["care_reserve"]["pea"] < care.bucket.wrapper_split["pea"] - 1.0


def test_chosen_weights_respect_equity_cap(proposals):
    profiles = load_profiles()
    etfs = {e.ticker: e for e in load_etfs()}
    for p in proposals.values():
        for bp in p.buckets:
            b = bp.bucket
            w = bp.methods[bp.chosen].weights
            if b.safe_share >= 1 or w.empty:
                continue
            cap = min(1.0, profiles[b.risk].max_equity / (1 - b.safe_share))
            eq = sum(v for t, v in w.items() if etfs[t].asset_class.startswith("equity_"))
            assert eq <= cap + 1e-4


def test_c3_structured_carved_from_longest_bucket(proposals):
    p = proposals["c3"]
    s = p.structured
    assert s.included and s.product_id
    key = f"structured:{s.product_id}"
    assert p.totals[s.wrapper][key] == pytest.approx(s.amount, abs=1.0)
    longest = max(p.buckets, key=lambda bp: bp.bucket.horizon_years)
    assert longest.holdings_eur[s.wrapper][key] == pytest.approx(s.amount, abs=1.0)
    assert any("structured" in r.lower() for r in longest.bucket.rules)
    others = [bp for bp in p.buckets if bp is not longest]
    assert all(key not in prods for bp in others for prods in bp.holdings_eur.values())


def test_c4_structured_excluded_everywhere(proposals):
    p = proposals["c4"]
    assert not p.structured.included
    for holdings in [p.totals, *(bp.holdings_eur for bp in p.buckets)]:
        assert not any(k.startswith("structured:") for prods in holdings.values() for k in prods)
    f = proposal_facts(p)
    assert f["structured"]["included"] is False
    assert f["structured"]["reasons"]
    assert "amount_eur" not in f["structured"]
    assert "structured:" not in json.dumps(f["totals"])
    assert all("structured:" not in json.dumps(g) for g in f["goals"])


def _numeric_leaves(obj, key=None):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _numeric_leaves(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _numeric_leaves(v, key)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield key, obj


def test_facts_json_serialisable_and_naming(proposals):
    for p in proposals.values():
        f = proposal_facts(p)
        assert json.loads(json.dumps(f)) == f
        leaves = list(_numeric_leaves(f))
        assert leaves
        for k, v in leaves:
            assert k == "age" or k.endswith(NUMERIC_SUFFIXES), k
            if k.endswith("_pct"):
                assert round(v, 1) == v
            if k.endswith(("_eur", "_year", "_count")) or k == "age":
                assert isinstance(v, int), (k, v)
            if k.endswith("_year"):
                assert 1000 <= v <= 9999


def test_facts_content(proposals):
    s = load_settings()
    f = proposal_facts(proposals["c3"])
    assert f["disclaimer"] == s.disclaimer
    assert f["client"]["name"] == CLIENTS["c3"].name and f["client"]["age"] == 45
    assert f["profile"]["risk_profile_count"] == 6
    assert f["emergency"]["target_eur"] == round(proposals["c3"].emergency.target)
    g = f["goals"][0]
    for key in (
        "label",
        "target_today_eur",
        "target_nominal_eur",
        "goal_year",
        "chosen_method",
        "expected_return_pct",
        "volatility_pct",
        "max_drawdown_pct",
        "probability_pct",
        "p10_eur",
        "p50_eur",
        "p90_eur",
        "monthly_contribution_eur",
        "wrappers",
        "top_holdings",
    ):
        assert key in g, key
    st = f["structured"]
    assert st["included"] is True and st["amount_eur"] > 0
    for key in ("product_name", "prob_capital_loss_pct", "annualised_expected_return_pct"):
        assert key in st
    assert st["describe"] and st["reasons"]
    assert f["totals"]["total_eur"] == round(CLIENTS["c3"].liquid_assets)
    assert set(f["appropriateness"]) == {"etf_equity", "etf_bond"}


def test_method_override(con):
    c = CLIENTS["c1"]
    gid = c.goals[0].goal_id
    p = build_proposal(c, con, method_override={gid: "markowitz"})
    assert p.buckets[0].chosen == "markowitz"
    with pytest.raises(ValueError):
        build_proposal(c, con, method_override={gid: "magic"})


def test_save_proposal_roundtrip(proposals):
    con = load_snapshot()
    p = proposals["c2"]
    save_proposal(con, p)
    row = con.execute(
        "SELECT payload_json FROM fact_proposals WHERE client_id = ? ORDER BY created_at DESC",
        ["c2"],
    ).fetchone()
    assert json.loads(row[0]) == proposal_facts(p)


def _small_sleeve_client():
    """Structured-eligible client whose longest goal is funded only by monthly saving."""
    base = CLIENTS["c3"].model_dump()
    base.update(
        client_id="small",
        liquid_assets=80000,
        monthly_saving=1000,
        monthly_expenses=2000,
        original_proposal=None,
        proposal_date=None,
        goals=[
            {
                "goal_id": "home",
                "label": "Home deposit",
                "target_today_eur": 80000,
                "date": date(2031, 10, 31),
                "priority": "essential",
            },
            {
                "goal_id": "ret",
                "label": "Retirement",
                "target_today_eur": 150000,
                "date": date(2046, 10, 31),
                "priority": "aspirational",
            },
        ],
    )
    from wealthadvisor.clients.models import Client

    return Client.model_validate(base)


def test_structured_not_included_when_sleeve_below_minimum_ticket(con):
    p = build_proposal(_small_sleeve_client(), con)
    longest = max(p.buckets, key=lambda bp: bp.bucket.horizon_years)
    assert longest.bucket.funding_now * (1 - longest.bucket.safe_share) < 1000
    s = p.structured
    assert not s.included and s.amount == 0 and s.payoff is None
    assert any("minimum 1,000 EUR" in r for r in s.reasons)
    assert not any(k.startswith("structured:") for prods in p.totals.values() for k in prods)
    assert not any("Structured product" in r for bp in p.buckets for r in bp.bucket.rules)
    f = proposal_facts(p)["structured"]
    assert f["included"] is False and "product_name" not in f


def test_facts_include_client_saving_and_liquid_assets(proposals):
    c = CLIENTS["c2"]
    f = proposal_facts(proposals["c2"])["client"]
    assert f["monthly_saving_eur"] == round(c.monthly_saving)
    assert f["liquid_assets_eur"] == round(c.liquid_assets)
