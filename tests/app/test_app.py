from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from wealthadvisor.clients.models import list_sample_clients

ROOT = Path(__file__).resolve().parents[2]
PAGE = str(ROOT / "app" / "pages" / "1_New_client.py")
HOME = str(ROOT / "app" / "Home.py")
CLIENTS = ["c1", "c2", "c3", "c4"]


def _run(client_id=None):
    at = AppTest.from_file(PAGE, default_timeout=180).run()
    if client_id:
        at.selectbox(key="client_select").select_index(CLIENTS.index(client_id)).run()
    return at


@pytest.mark.parametrize("cid", CLIENTS)
def test_new_client_page_runs_for_each_sample(cid):
    at = _run(cid)
    assert not at.exception, [e.value for e in at.exception]
    assert any("not investment advice" in c.value for c in at.caption)


@pytest.mark.parametrize("page", ["3_Product_universe", "4_Data_quality", "5_About"])
def test_static_pages_run(page):
    at = AppTest.from_file(str(ROOT / "app" / "pages" / f"{page}.py"), default_timeout=120).run()
    assert not at.exception, [e.value for e in at.exception]


def test_home_runs():
    at = AppTest.from_file(HOME, default_timeout=120).run()
    assert not at.exception


def test_method_switch_changes_displayed_number():
    at = _run("c2")
    sel = next(s for s in at.selectbox if s.key and s.key.startswith("method_"))
    before = [m.value for m in at.metric if m.label == "Expected return (bucket)"]
    other = next(o for o in ("markowitz", "black_litterman", "hrp") if o != sel.value)
    sel.select(other).run()
    assert not at.exception, [e.value for e in at.exception]
    after = [m.value for m in at.metric if m.label == "Expected return (bucket)"]
    assert before != after


def test_blank_client_form_submits():
    at = _run()
    at.selectbox(key="client_select").select("Blank client").run()
    assert not at.exception, [e.value for e in at.exception]
    at.button(key="blank_submit").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("Risk profile" in m.label for m in at.metric)


REVIEW = str(ROOT / "app" / "pages" / "2_Annual_review.py")


REVIEW_CLIENTS = ["c2", "c3"]  # sample clients with an existing portfolio


def _review(client_id):
    at = AppTest.from_file(REVIEW, default_timeout=180).run()
    at.selectbox(key="review_client").select_index(REVIEW_CLIENTS.index(client_id)).run()
    return at


def test_review_c2_has_trades_table():
    at = _review("c2")
    assert not at.exception, [e.value for e in at.exception]
    assert any("Action" in list(d.value.columns) for d in at.dataframe)
    assert not any("No rebalancing needed" in i.value for i in at.info)
    assert any("not investment advice" in c.value for c in at.caption)


def test_review_c3_no_rebalancing():
    at = _review("c3")
    assert not at.exception, [e.value for e in at.exception]
    assert any("No rebalancing needed" in i.value for i in at.info)


def test_review_lists_only_clients_with_a_portfolio():
    at = AppTest.from_file(REVIEW, default_timeout=180).run()
    assert not at.exception, [e.value for e in at.exception]
    names = {c.client_id: c.name for c in list_sample_clients()}
    assert at.selectbox(key="review_client").options == [names[c] for c in REVIEW_CLIENTS]
    # the default selection opens a real review, not a dead end
    assert not any("No existing portfolio" in i.value for i in at.info)
    assert any("Action" in list(d.value.columns) for d in at.dataframe)


def test_review_editing_answer_flips_profile_changed():
    at = _review("c2")
    assert not any("profile changed" in w.value.lower() for w in at.warning)
    at.selectbox(key="rq_c2_loss_capacity").select("low")
    at.button(key="reprofile_submit").click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert any("profile changed" in w.value.lower() for w in at.warning)


def _blank(**inputs):
    at = _run()
    at.selectbox(key="client_select").select("Blank client").run()
    for key, value in inputs.items():
        at.number_input(key=key).set_value(value)
    at.button(key="blank_submit").click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_blank_client_defaults_give_meaningful_probabilities():
    at = _blank()
    probs = [m.value for m in at.metric if m.label == "Probability of reaching it"]
    assert len(probs) == 2, probs  # both default goals are on
    for v in probs:
        assert 0.3 < float(v.rstrip("%")) / 100 < 0.95, probs
        assert "." in v  # one decimal


def test_unfunded_bucket_shows_message_instead_of_fan_chart():
    at = _blank(blank_liquid=5000, blank_saving=0)
    assert (
        sum("Not funded: nothing left after higher-priority goals." in i.value for i in at.info)
        == 2
    )


def test_app_probabilities_have_one_decimal_and_loss_label():
    at = _review("c2")
    goals = next(d.value for d in at.dataframe if "Probability now (%)" in d.value.columns)
    vals = list(goals["Probability now (%)"]) + list(goals["Probability before (%)"])
    assert any(v != round(v) for v in vals)  # not rounded to whole percents
    assert all(round(v, 1) == v for v in vals)
    at = _run("c3")
    labels = [m.label for m in at.metric]
    assert "Simulated probability of capital loss (excluding issuer default)" in labels
