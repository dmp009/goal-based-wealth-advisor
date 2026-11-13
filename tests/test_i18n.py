import pytest

from wealthadvisor.clients.models import list_sample_clients
from wealthadvisor.data.snapshot import load_snapshot
from wealthadvisor.i18n import Msg, asset_class_label, product_name, render
from wealthadvisor.proposal import build_proposal

CLIENTS = {c.client_id: c for c in list_sample_clients()}


@pytest.fixture(scope="module")
def proposals():
    con = load_snapshot()
    return {cid: build_proposal(c, con) for cid, c in CLIENTS.items()}


def test_english_templates_reproduce_engine_strings(proposals):
    for p in proposals.values():
        pr = p.profile
        assert [m.render("en") for m in pr.rules_fired_msgs] == pr.rules_fired
        assert [m.render("en") for m in pr.constraints_msgs] == pr.constraints
        for s in p.suitability.values():
            assert [m.render("en") for m in s.reason_msgs] == s.reasons
            assert [m.render("en") for m in s.warning_msgs] == s.warnings
        st = p.structured
        assert [m.render("en") for m in st.reason_msgs] == st.reasons
        assert [m.render("en") for m in p.structured_warning_msgs] == p.structured_warnings
        if st.payoff is not None:
            assert st.payoff.describe_msg.render("en") == st.payoff.describe


def test_french_renderings_differ_and_use_french_numbers(proposals):
    p = proposals["c1"]
    fr = [m.render("fr") for m in p.profile.constraints_msgs]
    assert fr and all("profil" in s for s in fr)
    m = Msg(code="structured.reduced", params={"before": 11100.0, "after": 5250.5})
    assert render(m, "fr").startswith("Montant du produit structuré ramené de 11 100 € à 5 250 €")
    h = render("cap.horizon_3_to_5y", "fr", horizon=4.44, cap=3)
    assert "4,4 ans" in h
    assert render(Msg(code="cap.loss_capacity_low", params={"cap": 3, "not_binding": 2}), "fr") == (
        "Capacité à subir des pertes faible : profil plafonné à 3 (non contraignant, profil déjà à 2)."
    )


def test_every_french_template_exists():
    from wealthadvisor.i18n import TEMPLATES

    for code, t in TEMPLATES.items():
        assert set(t) == {"en", "fr"}, code


def test_labels():
    assert product_name("autocall", "fr") == "Autocall sur l'Euro Stoxx 50"
    assert asset_class_label("equity_world", "fr") == "Actions monde"
    assert asset_class_label("unknown_cls", "en") == "unknown cls"
