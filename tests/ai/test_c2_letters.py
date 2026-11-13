"""Sample EN/FR letters built from c2's real facts must pass numeric verification."""

import pytest

from wealthadvisor.ai.documents import generate
from wealthadvisor.ai.numbers import verify
from wealthadvisor.clients.models import list_sample_clients
from wealthadvisor.data.snapshot import load_snapshot
from wealthadvisor.pipeline import ai as run_ai
from wealthadvisor.proposal import build_proposal, proposal_facts


@pytest.fixture(scope="module")
def facts():
    c = {x.client_id: x for x in list_sample_clients()}["c2"]
    return proposal_facts(build_proposal(c, load_snapshot()))


def fr_eur(n):
    return f"{n:,}".replace(",", " ") + " €"


def fr_pct(x):
    return f"{x:.1f}".replace(".", ",") + " %"


def letter_en(f):
    g = f["goals"][0]
    return (
        "# Your investment proposal\n\n"
        f"Dear Isabelle and Marc,\n\nYour daughter's studies goal, due in {g['goal_year']}, "
        f"targets €{g['target_nominal_eur']:,} (about {g['target_today_eur']:,} EUR in today's money) "
        f"over {g['horizon_years_count']} years. We propose to invest €{g['funding_now_eur']:,} "
        f"today with an expected return of {g['expected_return_pct']} % a year. In our simulations "
        f"the chance of reaching the target is {g['probability_pct']} %; the middle outcome is "
        f"€{g['p50_eur']:,}, between €{g['p10_eur']:,} and €{g['p90_eur']:,}. In a bad "
        f"stretch the risky part has lost as much as {abs(g['max_drawdown_pct'])} % in the past. "
        f"Your emergency fund of €{f['emergency']['funded_eur']:,} is fully funded.\n\n"
        "These figures are simulations, not promises.\n\n"
        f"{f['disclaimer']['en']}"
    )


def letter_fr(f):
    g = f["goals"][0]
    return (
        "# Votre proposition d'investissement\n\n"
        f"Chère Isabelle, cher Marc,\n\nVotre objectif études, prévu en {g['goal_year']}, vise "
        f"{fr_eur(g['target_nominal_eur'])} (soit {fr_eur(g['target_today_eur'])} d'aujourd'hui) "
        f"sur {g['horizon_years_count']} ans. Nous vous proposons d'investir "
        f"{fr_eur(g['funding_now_eur'])}, pour un rendement attendu de "
        f"{fr_pct(g['expected_return_pct'])} par an. Dans nos simulations, vous avez "
        f"{fr_pct(g['probability_pct'])} de chances d'atteindre l'objectif ; le scénario central "
        f"est de {fr_eur(g['p50_eur'])}, entre {fr_eur(g['p10_eur'])} et {fr_eur(g['p90_eur'])}. "
        f"Votre épargne de précaution de {fr_eur(f['emergency']['funded_eur'])} est constituée.\n\n"
        "Ces chiffres sont des simulations, pas des promesses.\n\n"
        f"{f['disclaimer']['fr']}"
    )


def test_c2_letters_verify(facts):
    assert verify(letter_en(facts), "en", facts) == []
    assert verify(letter_fr(facts), "fr", facts) == []


def test_c2_letter_with_wrong_number_flagged(facts):
    bad = letter_en(facts).replace(f"{facts['goals'][0]['probability_pct']} %", "65 %")
    assert any("65" in e for e in verify(bad, "en", facts))


def test_pipeline_ai_generates_four_docs_per_client(facts, tmp_path):
    class Echo:
        def write_document(self, prompt):
            lang = "French" if "Write in French" in prompt else "English"
            body = letter_fr(facts) if lang == "French" else letter_en(facts)
            return {"title": "T", "body": body}

    docs = run_ai(["c2"], refresh=False, llm=Echo(), cache_dir=tmp_path)
    assert len(docs) == 4
    assert {(d.doc_type, d.lang) for d in docs} == {
        ("proposal_advisor", "en"),
        ("proposal_advisor", "fr"),
        ("proposal_client", "en"),
        ("proposal_client", "fr"),
    }
    assert all(d.verified for d in docs)
    again = run_ai(["c2"], refresh=False, llm=None, cache_dir=tmp_path)
    assert len(again) == 4


def test_pipeline_main_without_key_exits_cleanly(monkeypatch, caplog):
    from wealthadvisor.pipeline import main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    main(["ai"])
    assert "ANTHROPIC_API_KEY" in caplog.text


def test_generate_signature_smoke(facts, tmp_path):
    assert generate("proposal_client", "en", facts, None, False, tmp_path) is None
