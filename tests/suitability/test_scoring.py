from datetime import date

import pytest

from wealthadvisor.clients.models import list_sample_clients
from wealthadvisor.suitability.products import check_product
from wealthadvisor.suitability.scoring import score_profile

TODAY = date(2026, 10, 31)
CLIENTS = {c.client_id: c for c in list_sample_clients()}


@pytest.mark.parametrize("cid,expected", [("c1", 3), ("c2", 4), ("c3", 6), ("c4", 2)])
def test_sample_client_profiles(cid, expected):
    assert score_profile(CLIENTS[cid], TODAY).profile == expected


def test_today_is_required():
    with pytest.raises(TypeError):
        score_profile(CLIENTS["c1"])  # type: ignore[call-arg]


def test_c1_capped_by_horizon():
    r = score_profile(CLIENTS["c1"], TODAY)
    assert r.profile == 3 and r.raw_score > 3.5
    assert any("horizon" in s for s in r.rules_fired)


def test_short_horizon_high_tolerance_capped_at_2():
    c = CLIENTS["c3"].model_copy(deep=True)
    c.goals = [g.model_copy(update={"date": date(2028, 10, 31)}) for g in c.goals[:1]]
    r = score_profile(c, TODAY)
    assert r.profile == 2
    assert any("less than 3 years" in s and "2" in s for s in r.rules_fired)


def test_low_loss_capacity_caps_at_3():
    c = CLIENTS["c3"].model_copy(deep=True)
    c.answers["loss_capacity"] = "low"
    r = score_profile(c, TODAY)
    assert r.profile == 3
    assert any("Loss capacity" in s for s in r.rules_fired)


def test_no_equity_knowledge_caps_at_4():
    c = CLIENTS["c3"].model_copy(deep=True)
    c.answers["etf_equity"] = "none"
    r = score_profile(c, TODAY)
    assert r.profile == 4 and r.knowledge["etf_equity"] is False
    assert any("equity ETFs" in s for s in r.rules_fired)


def test_uncapped_client_has_no_rules():
    assert score_profile(CLIENTS["c2"], TODAY).rules_fired == []


def test_structured_c4_excluded_with_reasons():
    c4 = CLIENTS["c4"]
    p = score_profile(c4, TODAY)
    s = check_product("structured", c4, p, 7.2)
    assert not s.included and len(s.reasons) >= 1


def test_structured_c3_included():
    c3 = CLIENTS["c3"]
    p = score_profile(c3, TODAY)
    s = check_product("structured", c3, p, 20.0)
    assert s.included


def test_each_structured_condition_has_own_reason():
    c4 = CLIENTS["c4"]
    s = check_product("structured", c4, score_profile(c4, TODAY), 7.2)
    assert len(s.reasons) == 3


def test_basic_families():
    c4 = CLIENTS["c4"]
    p = score_profile(c4, TODAY)
    assert check_product("livret_a", c4, p, 1).included
    assert check_product("fonds_euros", c4, p, 1).included
    assert check_product("etf_bond", c4, p, 1).included
    assert check_product("etf_equity", c4, p, 1).included  # profile 2
    p1 = p.model_copy(update={"profile": 1})
    s = check_product("etf_equity", c4, p1, 1)
    assert not s.included and s.reasons
    with pytest.raises(ValueError):
        check_product("crypto", c4, p, 1)


def test_c4_constraints_list_non_binding_caps():
    r = score_profile(CLIENTS["c4"], TODAY)
    assert r.rules_fired == []
    assert any("Loss capacity" in s and "not binding" in s for s in r.constraints)
    assert any("equity ETFs" in s and "not binding" in s for s in r.constraints)


def test_binding_cap_in_both_lists():
    r = score_profile(CLIENTS["c1"], TODAY)
    assert set(r.rules_fired) <= set(r.constraints)


def test_c4_equity_and_bond_warnings():
    c4 = CLIENTS["c4"]
    p = score_profile(c4, TODAY)
    s = check_product("etf_equity", c4, p, 7.2)
    assert s.included and any("no knowledge of equity ETFs" in w for w in s.warnings)
    assert check_product("etf_bond", c4, p, 7.2).warnings == []  # c4 has basic bond knowledge
    assert check_product("livret_a", c4, p, 7.2).warnings == []


def test_missing_answer_names_question():
    c = CLIENTS["c2"].model_copy(deep=True)
    del c.answers["risk_reaction"]
    with pytest.raises(ValueError, match="risk_reaction"):
        score_profile(c, TODAY)
