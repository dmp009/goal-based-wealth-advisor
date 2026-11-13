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


@pytest.fixture(scope="module")
def review_built():
    from wealthadvisor.review.engine import build_review, review_facts

    client = next(c for c in list_sample_clients() if c.client_id == "c2")
    r = build_review(client, load_snapshot())
    return r, review_facts(r)


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_review_pdf_disclaimer_and_content(review_built, lang):
    from wealthadvisor.outputs.pdf import review_pdf

    r, facts = review_built
    pdf = review_pdf(r, facts, {"en": None, "fr": None}, lang)
    assert pdf.startswith(b"%PDF")
    text = _text(pdf).replace("\n", " ")
    assert load_settings().disclaimer[lang] in text
    assert r.client.name in text and "€" in text
    if lang == "fr":
        assert "Revue annuelle" in text


def test_review_pdf_verified_letter_accents(review_built):
    from wealthadvisor.outputs.pdf import review_pdf

    r, facts = review_built
    letter = Document(
        "review_client", "fr", "Votre revue", "Chère cliente, à très bientôt.", "k", True, []
    )
    text = _text(review_pdf(r, facts, {"fr": letter}, "fr"))
    assert "Chère cliente" in text
    bad = Document("review_client", "en", "T", "SECRETBODY", "k", False, ["x"])
    assert "SECRETBODY" not in _text(review_pdf(r, facts, {"en": bad}, "en"))


def _proposal_text(cid: str, lang: str) -> str:
    client = next(c for c in list_sample_clients() if c.client_id == cid)
    p = build_proposal(client, load_snapshot())
    return _text(proposal_pdf(p, proposal_facts(p), {}, lang)).replace("\n", " ")


@pytest.mark.parametrize("cid", ["c1", "c3"])
def test_french_proposal_pdf_has_no_english_engine_text(cid):
    text = _proposal_text(cid, "fr")
    for en in (
        "Structured products require",
        "Longest goal horizon",
        "Autocall on the Euro",
        "profile capped",
        "Issuer credit risk",
    ):
        assert en not in text, en


def test_french_review_pdf_has_no_english_asset_classes(review_built):
    from wealthadvisor.outputs.pdf import review_pdf

    r, facts = review_built
    text = _text(review_pdf(r, facts, {}, "fr")).replace("\n", " ")
    for en in ("equity world", "safe", "equity europe"):
        assert en not in text, en
    assert "Actions monde" in text or "Actifs sécurisés" in text


@pytest.mark.parametrize(
    "lang,heading,warning,emergency",
    [
        ("en", "Appropriateness warnings", "no knowledge of equity ETFs", "Emergency fund"),
        (
            "fr",
            "Avertissements d'adéquation",
            "aucune connaissance des ETF actions",
            "Épargne de précaution",
        ),
    ],
)
def test_proposal_pdf_shows_appropriateness_warnings_and_emergency_fund(
    lang, heading, warning, emergency
):
    text = " ".join(_proposal_text("c4", lang).split())
    assert heading in text
    assert warning in text
    assert emergency in text


def test_proposal_pdf_flags_goals_at_risk():
    client = next(c for c in list_sample_clients() if c.client_id == "c3")
    p = build_proposal(client, load_snapshot())
    facts = proposal_facts(p)
    assert any(g["shortfall_flag"] for g in facts["goals"])
    for lang, marker in (("en", "At risk (< 50 %)"), ("fr", "Objectif à risque (< 50 %)")):
        text = " ".join(_text(proposal_pdf(p, facts, {}, lang)).split())
        assert text.count(marker) == sum(g["shortfall_flag"] for g in facts["goals"])


@pytest.mark.parametrize(
    "lang,loss,target",
    [
        (
            "en",
            "Simulated probability of capital loss (excluding issuer default)",
            "Target (nominal)",
        ),
        (
            "fr",
            "Probabilité simulée de perte en capital (hors défaut de l'émetteur)",
            "Cible (nominale)",
        ),
    ],
)
def test_proposal_pdf_explicit_labels(lang, loss, target):
    text = " ".join(_proposal_text("c3", lang).split())
    assert loss in text
    assert target in text


@pytest.mark.parametrize(
    "lang,target", [("en", "Target (today's €)"), ("fr", "Cible (€ d'aujourd'hui)")]
)
def test_review_pdf_target_label(review_built, lang, target):
    from wealthadvisor.outputs.pdf import review_pdf

    r, facts = review_built
    assert target in " ".join(_text(review_pdf(r, facts, {}, lang)).split())
