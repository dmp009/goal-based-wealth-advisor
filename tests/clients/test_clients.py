from datetime import date

from wealthadvisor.clients.models import Client, list_sample_clients, load_client
from wealthadvisor.config import REPO_ROOT, load_etfs


def test_list_sample_clients():
    clients = list_sample_clients()
    assert [c.client_id for c in clients] == ["c1", "c2", "c3", "c4"]
    assert all(isinstance(c, Client) for c in clients)


def test_proposals_only_for_c2_c3():
    by = {c.client_id: c for c in list_sample_clients()}
    assert by["c1"].original_proposal is None and by["c1"].proposal_date is None
    assert by["c4"].original_proposal is None and by["c4"].proposal_date is None
    for cid in ("c2", "c3"):
        assert by[cid].proposal_date == date(2025, 4, 30)
        assert by[cid].original_proposal["livret_a"]["livret_a"] > 0


FILES = {"c2": "c2_couple_retirement.json", "c3": "c3_business_owner.json"}


def test_proposal_tickers_valid_and_pea_eligible():
    etfs = {e.ticker: e for e in load_etfs()}
    for cid in ("c2", "c3"):
        c = load_client(REPO_ROOT / "data" / "clients" / FILES[cid])
        for wrapper, lines in c.original_proposal.items():
            for key in lines:
                if key in ("livret_a", "fonds_euros") or key.startswith("structured:"):
                    continue
                assert key in etfs
                if wrapper == "pea":
                    assert etfs[key].pea_eligible is True
