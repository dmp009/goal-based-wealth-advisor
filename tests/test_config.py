import os

import pytest

from wealthadvisor import config

ASSET_CLASSES = {
    "equity_world", "equity_europe", "equity_us", "equity_em",
    "bond_gov_euro", "bond_corp_euro", "bond_inflation_euro",
}


def test_profiles_table_exact():
    p = config.load_profiles()
    assert sorted(p) == [1, 2, 3, 4, 5, 6, 7]
    got = [(r.profile, r.vol_cap, r.max_equity, r.min_safe_share) for r in p.values()]
    assert got == [
        (1, 0.02, 0.00, 0.80), (2, 0.04, 0.20, 0.60), (3, 0.07, 0.40, 0.40),
        (4, 0.10, 0.60, 0.25), (5, 0.13, 0.75, 0.10), (6, 0.16, 0.90, 0.00),
        (7, 0.20, 1.00, 0.00),
    ]


def test_etf_count_and_cma_coverage():
    etfs = config.load_etfs()
    cma = config.load_cma()
    assert 12 <= len(etfs) <= 15
    assert set(cma) == ASSET_CLASSES
    assert {e.asset_class for e in etfs} == ASSET_CLASSES
    assert all(e.ticker.endswith(".PA") for e in etfs)


@pytest.mark.parametrize("ac", ["equity_world", "equity_europe"])
def test_pea_eligible_etf_per_equity_class(ac):
    assert any(e.pea_eligible and e.asset_class == ac for e in config.load_etfs())


def test_proxies_exist_and_same_class():
    etfs = {e.ticker: e for e in config.load_etfs()}
    for e in etfs.values():
        if e.proxy:
            assert etfs[e.proxy].asset_class == e.asset_class


def test_reference_weights_sum_to_one():
    w = config.load_reference_weights()
    assert set(w) == ASSET_CLASSES
    assert sum(w.values()) == pytest.approx(1.0)


def test_settings_defaults():
    s = config.load_settings()
    assert (s.seed, s.n_paths, s.inflation, s.drift_band) == (42, 10000, 0.02, 0.05)
    assert s.disclaimer == {
        "en": "Educational project — not investment advice",
        "fr": "Projet pédagogique — pas un conseil en investissement",
    }


def test_rates_sources():
    r = config.load_rates()
    for k in ("fonds_euros", "livret_a_rate", "livret_a_cap", "pea_contribution_cap"):
        assert r[k]["source"] and r[k]["as_of"]
    assert r["fonds_euros"]["value"] == 0.025
    assert r["livret_a_cap"]["value"] == 22950
    assert r["pea_contribution_cap"]["value"] == 150000


def test_tax_rules():
    t = config.load_tax_rules()
    assert t["pea"]["rate_before_5y"] == 0.30 and t["pea"]["rate_after_5y"] == 0.172
    av = t["assurance_vie"]
    assert (av["rate_before_8y"], av["rate_after_8y"]) == (0.30, 0.247)
    assert (av["allowance_single"], av["allowance_couple"]) == (4600, 9200)
    assert t["cto"]["rate"] == 0.30 and t["livret_a"]["rate"] == 0


def test_structured_and_questionnaire():
    s = config.load_structured()
    assert s["templates"]["autocall_sx5e"]["barrier"] == 0.60
    assert s["templates"]["cpn_sx5e"]["participation"] == 0.5
    assert s["dividend_yield"] == 0.03 and s["max_share"] == 0.15
    assert s["eligibility"] == {"min_profile": 4, "min_horizon_years": 8}
    assert isinstance(config.load_questionnaire(), dict)


def test_paths_independent_of_cwd(tmp_path):
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        assert len(config.load_etfs()) >= 12
    finally:
        os.chdir(old)
