"""Adversarial strings against c2's real facts (reviewer round 1)."""

import pytest

from wealthadvisor.ai import documents
from wealthadvisor.ai.numbers import verify
from wealthadvisor.clients.models import list_sample_clients
from wealthadvisor.data.snapshot import load_snapshot
from wealthadvisor.proposal import build_proposal, proposal_facts


@pytest.fixture(scope="module")
def facts():
    c = {x.client_id: x for x in list_sample_clients()}["c2"]
    return proposal_facts(build_proposal(c, load_snapshot()))


FAIL_OPEN = [
    ("The target is €1.2m.", "en"),
    ("About €99bn invested.", "en"),
    ("Over 17y it grows.", "en"),
    ("Over 27yrs it grows.", "en"),
    ("A return of 61pct.", "en"),
    ("Leverage of 2,5x.", "en"),
    ("Around the 2060s.", "en"),
    ("Soit 1,2 M€ au total.", "fr"),
    ("Soit 3 Md€ au total.", "fr"),
    ("Product AB7Z.PA is great.", "en"),
]


@pytest.mark.parametrize("text,lang", FAIL_OPEN)
def test_fail_open_strings_now_flagged(facts, text, lang):
    assert verify(text, lang, facts) != []


def test_real_tickers_and_percentiles_allowed(facts):
    assert verify("We hold AM3A.PA and CRP.PA; see the P10–P90 range.", "en", facts) == []


def test_goal_scoping(facts):
    # 98.0 % / 2040 are not studies facts; goal_year 2030 belongs to studies
    ok = "The studies goal is due in 2030."
    assert verify(ok, "en", facts) == []
    assert verify("The studies goal has a 98.0 % chance.", "en", facts) != []
    assert verify("The studies goal is due in 2040.", "en", facts) != []
    ret = facts["goals"][1]
    other = f"The studies goal reaches {ret['probability_pct']} %."
    assert ret["probability_pct"] != facts["goals"][0]["probability_pct"]
    assert verify(other, "en", facts) != []
    # same sentence without goal naming uses global matching
    assert verify(f"The chance is {ret['probability_pct']} %.", "en", facts) == []
    # heading scoping
    text = f"## Studies\n- chance {ret['probability_pct']} %"
    assert verify(text, "en", facts) != []


def test_signs(facts):
    dd = abs(facts["goals"][0]["max_drawdown_pct"])
    assert verify(f"A drawdown of {dd} %.", "en", facts) == []
    assert verify(f"A drawdown of -{dd} %.", "en", facts) == []
    assert (
        verify(f"Expected return of -{facts['goals'][0]['expected_return_pct']} %.", "en", facts)
        != []
    )


def test_eur_pool_not_polluted(facts):
    assert verify("A fee of €3.", "en", facts) != []
    assert verify("A fee of €39.", "en", facts) != []
    assert verify("Monthly €1.", "en", facts) != []  # monthly_contribution_eur is 0: no min tol


def test_percent_precision(facts):
    p = facts["goals"][0]["probability_pct"]
    assert verify(f"{p + 0.3:.1f} %", "en", facts) != []
    assert verify(f"{round(p)} %", "en", facts) == []


def test_age_context(facts):
    age = facts["client"]["age"]
    assert verify(f"Vous avez {age} ans.", "fr", facts) == []
    assert verify(f"Vous avez {age + 5} ans.", "fr", facts) != []
    assert verify(f"aged {age + 5}", "en", facts) != []
    assert verify("sur 4 ans", "fr", facts) == []


def test_cache_key_includes_template(monkeypatch, tmp_path):
    k = documents.cache_key({"a": 1}, "proposal_client", "en")
    (tmp_path / "proposal_v1.md").write_text("different")
    monkeypatch.setattr(documents, "PROMPT_DIR", tmp_path)
    assert documents.cache_key({"a": 1}, "proposal_client", "en") != k


def test_pipeline_continues_on_runtime_error(tmp_path):
    from wealthadvisor.pipeline import ai

    class Boom:
        def write_document(self, prompt):
            raise RuntimeError("max_tokens")

    assert ai(["c2"], False, Boom(), tmp_path) == []


# ---------------------------------------------------------------- round 2

R2_FLAGGED = [
    ("Pour le master de votre fille, la probabilité est d'environ 98 %.", "fr"),
    ("## Objectif : master de votre fille\nProbabilité : 98,0 %", "fr"),
    ("## Retirement top-up capital\n### Overview\n- probability 50.7 %", "en"),
    ("Over 15y it grows.", "en"),
    ("Over 15yr it grows.", "en"),
    ("Over 15 yrs it grows.", "en"),
    ("A 15-year horizon.", "en"),
    ("Sur 15 ans.", "fr"),
    ("Over 25yrs.", "en"),
    ("The drawdown is +15.0 %.", "en"),
    ("Le 80e centile et le 85th percentile.", "fr"),
    ("Vous avez 14 ans d'horizon sur ce projet de 99 ans.", "fr"),
]


@pytest.mark.parametrize("text,lang", R2_FLAGGED)
def test_round2_flagged(facts, text, lang):
    assert verify(text, lang, facts) != []


def test_french_labels_in_facts(facts):
    assert all(g["label_fr"] for g in facts["goals"])
    assert facts["goals"][0]["label_fr"] == "Master de votre fille"


def test_french_scoping_positive(facts):
    g0 = facts["goals"][0]
    p = str(g0["probability_pct"]).replace(".", ",")
    assert verify(f"## Master de votre fille\nProbabilité : {p} %", "fr", facts) == []
    ret = facts["goals"][1]
    assert ret["probability_pct"] != g0["probability_pct"]
    q = str(ret["probability_pct"]).replace(".", ",")
    assert verify(f"## Master de votre fille\nProbabilité : {q} %", "fr", facts) != []


def test_nested_heading_scope_ends_at_same_level(facts):
    ret = facts["goals"][1]
    other = facts["goals"][0]
    text = f"## {ret['label']}\n### Overview\n- p {ret['probability_pct']} %\n## Notes\n- p {other['probability_pct']} %"
    assert verify(text, "en", facts) == []


def test_duration_units(facts):
    assert verify("## Master de votre fille\nSur 4 ans.", "fr", facts) == []
    assert verify("## Master de votre fille\nSur 15 ans.", "fr", facts) != []
    assert verify("Over 46 months, the studies goal.", "en", facts) == []


def test_percentiles_and_plus(facts):
    assert verify("Le 90e centile et le 90th percentile.", "fr", facts) == []
    assert verify("A gain of +3.7 %.", "en", facts) == []


def test_french_amounts_and_multipliers(facts):
    n = facts["emergency"]["funded_eur"]
    dot = f"{n:,}".replace(",", ".")
    assert verify(f"Épargne de {dot} €.", "fr", facts) == []
    assert verify("Soit 15 M€.", "fr", facts) != []
    assert verify("Soit 15 Mds €.", "fr", facts) != []
    assert verify("Soit 15 Mio €.", "fr", facts) != []


def test_pipeline_continues_on_any_exception(tmp_path):
    from wealthadvisor.pipeline import ai

    class Boom:
        def write_document(self, prompt):
            raise ValueError("api error")

    assert ai(["c2"], False, Boom(), tmp_path) == []
