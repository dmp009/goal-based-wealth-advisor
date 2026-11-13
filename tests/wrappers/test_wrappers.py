from datetime import date

import pytest

from wealthadvisor.clients.models import Client, Goal, list_sample_clients
from wealthadvisor.config import load_profiles, load_rates, load_settings
from wealthadvisor.suitability.scoring import score_profile
from wealthadvisor.wrappers.allocate import bucket_risk, inflate_target, plan_buckets
from wealthadvisor.wrappers.tax import tax_on_gain, weighted_average_cost

TODAY = date(2026, 10, 31)
RATES, SETTINGS, PROFILES = load_rates(), load_settings(), load_profiles()


def make_client(liquid, saving, goals, expenses=2000, household="single"):
    return Client(
        client_id="t",
        name="T",
        age=40,
        household=household,
        annual_income=50000,
        monthly_expenses=expenses,
        liquid_assets=liquid,
        debts=0,
        monthly_saving=saving,
        goals=[
            Goal(goal_id=g[0], label=g[0], target_today_eur=g[1], date=g[2], priority=g[3])
            for g in goals
        ],
        answers={},
    )


@pytest.mark.parametrize("p,h,exp", [(6, 2, 2), (6, 4, 3), (6, 6, 4), (6, 10, 6), (2, 10, 2)])
def test_bucket_risk(p, h, exp):
    assert bucket_risk(p, h) == exp


def test_tax():
    assert tax_on_gain("pea", 1000, 6, "single") == pytest.approx(172)
    assert tax_on_gain("pea", 1000, 3, "single") == pytest.approx(300)
    assert tax_on_gain("av", 10000, 9, "single") == pytest.approx(1333.8)
    assert tax_on_gain("av", 10000, 9, "couple") == pytest.approx(197.6)
    assert tax_on_gain("av", 1000, 3, "single") == pytest.approx(300)
    assert tax_on_gain("cto", 1000, 1, "single") == pytest.approx(300)
    assert tax_on_gain("livret_a", 1000, 1, "single") == 0
    assert tax_on_gain("cto", -50, 1, "single") == 0


def test_wac():
    assert weighted_average_cost([(10, 100), (10, 120)]) == pytest.approx(110)


def test_emergency_capped_and_shortfall():
    c = make_client(100000, 500, [("g", 50000, date(2036, 10, 31), "essential")], expenses=5000)
    plan = plan_buckets(c, 3, TODAY, RATES, SETTINGS)
    assert plan.emergency.target == 22950 and plan.emergency.funded == 22950
    c2 = make_client(3000, 500, [("g", 50000, date(2036, 10, 31), "essential")])
    e = plan_buckets(c2, 3, TODAY, RATES, SETTINGS).emergency
    assert e.target == 12000 and e.funded == 3000 and e.shortfall == 9000


def test_target_inflation():
    assert inflate_target(100000, 10, 0.02) == pytest.approx(121899.44, abs=0.01)
    c = make_client(50000, 500, [("g", 100000, date(2036, 10, 31), "essential")])
    b = plan_buckets(c, 6, TODAY, RATES, SETTINGS).buckets[0]
    assert b.target_nominal == pytest.approx(inflate_target(100000, b.horizon_years, 0.02))


def test_wrapper_split_sums_and_rules():
    c = make_client(
        60000,
        500,
        [
            ("a", 50000, date(2038, 10, 31), "essential"),
            ("b", 10000, date(2028, 1, 31), "aspirational"),
        ],
    )
    plan = plan_buckets(c, 6, TODAY, RATES, SETTINGS)
    for b in plan.buckets:
        assert sum(b.wrapper_split.values()) == pytest.approx(b.funding_now)
        assert b.rules
    long_b = next(b for b in plan.buckets if b.goal_id == "a")
    assert long_b.wrapper_split.get("pea", 0) > 0
    short = next(b for b in plan.buckets if b.goal_id == "b")
    assert short.risk == 2 and "pea" not in short.wrapper_split


def test_no_overfunding_and_surplus_to_longest():
    c = make_client(
        500000,
        0,
        [
            ("a", 10000, date(2028, 10, 31), "essential"),
            ("b", 10000, date(2036, 10, 31), "aspirational"),
        ],
    )
    plan = plan_buckets(c, 4, TODAY, RATES, SETTINGS)
    a = next(b for b in plan.buckets if b.goal_id == "a")
    bb = next(b for b in plan.buckets if b.goal_id == "b")
    assert a.funding_now == pytest.approx(a.target_nominal / (1 + 0.017) ** a.horizon_years)
    assert any("surplus" in r for r in bb.rules) and not any("surplus" in r for r in a.rules)
    assert bb.funding_now > bb.target_nominal
    assert a.funding_now + bb.funding_now == pytest.approx(500000 - 6000)


def test_pea_cap_shared():
    c = make_client(
        400000,
        0,
        [
            ("a", 400000, date(2040, 10, 31), "essential"),
            ("b", 400000, date(2041, 10, 31), "essential"),
        ],
    )
    plan = plan_buckets(c, 7, TODAY, RATES, SETTINGS)
    assert sum(b.wrapper_split.get("pea", 0) for b in plan.buckets) <= 150000 + 1e-6


def test_sample_clients_run():
    for cl in list_sample_clients():
        p = score_profile(cl, TODAY).profile
        plan = plan_buckets(cl, p, TODAY, RATES, SETTINGS)
        assert sum(b.funding_now for b in plan.buckets) == pytest.approx(
            max(0, cl.liquid_assets - plan.emergency.funded)
        )
        assert sum(b.monthly_contribution for b in plan.buckets) == pytest.approx(cl.monthly_saving)


def test_cumulative_caps_respected_for_samples():
    for cl in list_sample_clients():
        p = score_profile(cl, TODAY).profile
        plan = plan_buckets(cl, p, TODAY, RATES, SETTINGS)
        la = plan.emergency.funded
        pea = 0.0
        for b in plan.buckets:
            m = max(1.0, b.horizon_years * 12)
            la += b.wrapper_split.get("livret_a", 0) + m * b.monthly_split.get("livret_a", 0)
            pea += b.wrapper_split.get("pea", 0) + m * b.monthly_split.get("pea", 0)
            assert sum(b.monthly_split.values()) == pytest.approx(b.monthly_contribution)
        assert la <= 22950 + 1e-6
        assert pea <= 150000 + 1e-6


def test_livret_room_shared_with_emergency_fund():
    c = make_client(
        120000,
        0,
        [("short", 100000, date(2028, 4, 30), "essential")],
        expenses=4000,
    )
    plan = plan_buckets(c, 2, TODAY, RATES, SETTINGS)
    b = plan.buckets[0]
    assert plan.emergency.funded == 22950
    assert b.wrapper_split.get("livret_a", 0) == pytest.approx(0)
    assert b.wrapper_split.get("av", 0) > 0
    assert (
        sum(x.wrapper_split.get("livret_a", 0) for x in plan.buckets) + plan.emergency.funded
        <= 22950 + 1e-6
    )


def test_sequential_funding_by_date():
    c = make_client(
        30000,
        0,
        [
            ("late", 20000, date(2034, 10, 31), "essential"),
            ("early", 20000, date(2030, 10, 31), "essential"),
        ],
    )
    plan = plan_buckets(c, 4, TODAY, RATES, SETTINGS)
    early = next(b for b in plan.buckets if b.goal_id == "early")
    late = next(b for b in plan.buckets if b.goal_id == "late")
    assert early.funding_now == pytest.approx(early.target_nominal / 1.025**early.horizon_years)
    assert late.funding_now == pytest.approx(30000 - 6000 - early.funding_now)
