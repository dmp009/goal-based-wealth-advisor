import numpy as np
import plotly.graph_objects as go
import pytest

from app.charts import allocation_sunburst, fan_chart, method_comparison, payoff_histogram
from wealthadvisor.clients.models import list_sample_clients
from wealthadvisor.data.snapshot import load_snapshot
from wealthadvisor.proposal import build_proposal


@pytest.fixture(scope="module")
def proposal():
    client = next(c for c in list_sample_clients() if c.client_id == "c2")
    return build_proposal(client, load_snapshot())


def test_fan_chart(proposal):
    fig = fan_chart(proposal.buckets[0].goal, proposal.buckets[0].bucket.target_nominal)
    assert isinstance(fig, go.Figure) and len(fig.data) >= 3


def test_allocation_sunburst(proposal):
    fig = allocation_sunburst(proposal)
    assert isinstance(fig, go.Figure) and len(fig.data[0].labels) > 0


def test_method_comparison(proposal):
    fig = method_comparison(proposal.buckets[0])
    assert isinstance(fig, go.Figure) and len(fig.data) >= 1


def test_payoff_histogram():
    from wealthadvisor.structured.payoff import PayoffResult

    r = PayoffResult(np.array([1.0, 1.2, 0.7, 1.4]), np.array([0, 2, 0, 3]), 0.25, 1.1, "d")
    fig = payoff_histogram(r)
    assert isinstance(fig, go.Figure) and len(fig.data) >= 1


def test_review_charts():
    from app.charts import drift_bars, goal_probability_change
    from wealthadvisor.review.engine import build_review

    con = load_snapshot()
    client = next(c for c in list_sample_clients() if c.client_id == "c2")
    r = build_review(client, con)
    assert isinstance(drift_bars(r.drift, r.drift_band), go.Figure)
    assert isinstance(goal_probability_change(r, client.goals), go.Figure)
