import io

import pytest
from pypdf import PdfReader

from wealthadvisor.ai.documents import Document
from wealthadvisor.clients.models import list_sample_clients
from wealthadvisor.config import load_settings
from wealthadvisor.data.snapshot import load_snapshot
from wealthadvisor.outputs.pdf import proposal_pdf
from wealthadvisor.proposal import build_proposal, proposal_facts


@pytest.fixture(scope="module")
def built():
    con = load_snapshot()
    client = next(c for c in list_sample_clients() if c.client_id == "c2")
    p = build_proposal(client, con)
    return p, proposal_facts(p)


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_pdf_has_disclaimer_and_header(built, lang):
    p, facts = built
    pdf = proposal_pdf(p, facts, {"en": None, "fr": None}, lang)
    assert pdf.startswith(b"%PDF")
    text = _text(pdf).replace("\n", " ")
    assert load_settings().disclaimer[lang] in text
    assert p.client.name in text
    assert "€" in text


def test_pdf_includes_verified_letter_with_accents(built):
    p, facts = built
    letter = Document(
        "proposal_client",
        "fr",
        "Votre proposition",
        "Voilà : très bien, à côté, ça va, 5 000 €.",
        "k",
        True,
    )
    text = _text(proposal_pdf(p, facts, {"fr": letter, "en": None}, "fr"))
    for token in ("é", "à", "ç", "€", "Voilà"):
        assert token in text


def test_pdf_omits_unverified_letter(built):
    p, facts = built
    bad = Document("proposal_client", "en", "T", "SECRETBODY", "k", False, ["x"])
    text = _text(proposal_pdf(p, facts, {"en": bad, "fr": None}, "en"))
    assert "SECRETBODY" not in text
