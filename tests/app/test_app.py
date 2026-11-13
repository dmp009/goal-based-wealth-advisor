from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[2]
PAGE = str(ROOT / "app" / "pages" / "1_New_client.py")
HOME = str(ROOT / "app" / "streamlit_app.py")
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
