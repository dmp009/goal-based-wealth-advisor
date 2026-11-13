"""Proposal PDF (reportlab, built-in Helvetica: WinAnsi covers €, é, à, ç).

The client letter is included only when a *verified* document exists for the language; an
unverified body is never printed.
"""

from __future__ import annotations

import re
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from wealthadvisor.ai.documents import Document
from wealthadvisor.config import load_settings

NAVY = colors.HexColor("#1f3a5f")
_METHOD = {"markowitz": "Markowitz", "black_litterman": "Black-Litterman", "hrp": "HRP"}
_WRAPPER = {
    "livret_a": "Livret A",
    "pea": "PEA",
    "av": {"en": "Life insurance (AV)", "fr": "Assurance-vie (AV)"},
    "cto": {"en": "Securities account (CTO)", "fr": "Compte-titres (CTO)"},
    "fonds_euros": {"en": "of which fonds en euros", "fr": "dont fonds en euros"},
}
_T = {
    "en": {
        "title": "Investment proposal",
        "client": "Client",
        "date": "Data as of",
        "profile": "Risk profile",
        "of7": "of 7",
        "rules": "Rules applied",
        "none": "None",
        "wrappers": "Wrapper plan",
        "wrapper": "Wrapper",
        "amount": "Amount",
        "total": "Total",
        "goals": "Goals",
        "goal": "Goal",
        "target": "Target",
        "prob": "Probability",
        "method": "Method",
        "ret": "Exp. return",
        "vol": "Volatility",
        "structured": "Structured product",
        "excluded": "No structured product is proposed.",
        "included": "Product",
        "loss": "Probability of capital loss",
        "letter": "Client letter",
        "noletter": "No verified client letter is available for this proposal.",
        "page": "Page",
    },
    "fr": {
        "title": "Proposition d'investissement",
        "client": "Client",
        "date": "Données au",
        "profile": "Profil de risque",
        "of7": "sur 7",
        "rules": "Règles appliquées",
        "none": "Aucune",
        "wrappers": "Répartition par enveloppe",
        "wrapper": "Enveloppe",
        "amount": "Montant",
        "total": "Total",
        "goals": "Objectifs",
        "goal": "Objectif",
        "target": "Cible",
        "prob": "Probabilité",
        "method": "Méthode",
        "ret": "Rend. espéré",
        "vol": "Volatilité",
        "structured": "Produit structuré",
        "excluded": "Aucun produit structuré n'est proposé.",
        "included": "Produit",
        "loss": "Probabilité de perte en capital",
        "letter": "Lettre au client",
        "noletter": "Aucune lettre client vérifiée n'est disponible pour cette proposition.",
        "page": "Page",
    },
}


def _clean(text: str) -> str:
    """Map characters outside WinAnsi to safe equivalents (no missing-glyph boxes)."""
    text = text.replace(" ", " ").replace(" ", " ").replace("‑", "-")
    text = text.replace("−", "-").replace("→", "->").replace("≥", ">=")
    return text.encode("cp1252", errors="replace").decode("cp1252")


def _p(text: str, style) -> Paragraph:
    return Paragraph(escape(_clean(str(text))), style)


def _eur(x: float, lang: str) -> str:
    s = f"{round(x):,}"
    return s.replace(",", " ") + " €" if lang == "fr" else f"€{s}"


def _pct(x: float, lang: str) -> str:
    s = f"{x:.1f}"
    return (s.replace(".", ",") if lang == "fr" else s) + " %" if lang == "fr" else s + "%"


def _letter_flowables(doc: Document, styles) -> list:
    out = [_p(doc.title, styles["h3"]), Spacer(1, 4)]
    for raw in doc.body.split("\n"):
        line = raw.strip()
        if not line:
            out.append(Spacer(1, 4))
            continue
        line = re.sub(r"^#+\s*", "", line)
        line = re.sub(r"^[-*]\s+", "- ", line)
        line = line.replace("**", "").replace("__", "")
        out.append(_p(line, styles["body"]))
    return out


def _table(rows, widths, align_right_from=1) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (align_right_from, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f5f8")]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return t


def proposal_pdf(proposal, facts: dict, documents: dict, lang: str) -> bytes:
    if lang not in _T:
        raise ValueError(f"unsupported language {lang!r}")
    t = _T[lang]
    disclaimer = load_settings().disclaimer[lang]
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("t", parent=base["Title"], textColor=NAVY, fontSize=20),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=NAVY, spaceBefore=10),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], textColor=NAVY),
        "body": ParagraphStyle("b", parent=base["BodyText"], fontSize=9, leading=12),
        "cell": ParagraphStyle("c", parent=base["BodyText"], fontSize=8.5, leading=10),
        "small": ParagraphStyle("s", parent=base["BodyText"], fontSize=7.5, leading=9),
    }
    c = facts["client"]
    story: list = [
        _p(t["title"], styles["title"]),
        _p(f"{t['client']}: {c['name']} ({c['client_id']})", styles["body"]),
        _p(f"{t['date']}: {facts['as_of']}", styles["body"]),
        _p(f"{t['profile']}: {facts['profile']['risk_profile_count']} {t['of7']}", styles["h2"]),
        _p(t["rules"], styles["h3"]),
    ]
    rules = facts["profile"]["rules_fired"]
    for r in rules or [t["none"]]:
        story.append(_p("- " + r, styles["body"]))

    # wrapper plan
    story.append(_p(t["wrappers"], styles["h2"]))
    rows = [[t["wrapper"], t["amount"]]]
    for w in ("livret_a", "pea", "av", "cto", "fonds_euros"):
        v = facts["totals"].get(f"{w}_eur")
        if v:
            label = _WRAPPER[w] if isinstance(_WRAPPER[w], str) else _WRAPPER[w][lang]
            rows.append([label, _eur(v, lang)])
    rows.append([t["total"], _eur(facts["totals"]["total_eur"], lang)])
    story.append(_table(rows, [9 * cm, 4 * cm]))

    # goals
    story.append(_p(t["goals"], styles["h2"]))
    rows = [[t["goal"], t["target"], t["prob"], t["method"], t["ret"], t["vol"]]]
    for g in facts["goals"]:
        label = g["label_fr"] if lang == "fr" else g["label"]
        rows.append(
            [
                Paragraph(escape(_clean(label)), styles["cell"]),
                _eur(g["target_nominal_eur"], lang),
                _pct(g["probability_pct"], lang),
                _METHOD.get(g["chosen_method"], g["chosen_method"]),
                _pct(g["expected_return_pct"], lang),
                _pct(g["volatility_pct"], lang),
            ]
        )
    story.append(_table(rows, [5 * cm, 2.6 * cm, 2.2 * cm, 3 * cm, 2.2 * cm, 2.2 * cm]))

    # structured
    s = facts["structured"]
    story.append(_p(t["structured"], styles["h2"]))
    if s["included"]:
        story.append(
            _p(
                f"{t['included']}: {s['product_name']} - {_eur(s['amount_eur'], lang)}",
                styles["body"],
            )
        )
        if "prob_capital_loss_pct" in s:
            story.append(
                _p(f"{t['loss']}: {_pct(s['prob_capital_loss_pct'], lang)}", styles["body"])
            )
        if s.get("describe"):
            story.append(_p(s["describe"], styles["small"]))
    else:
        story.append(_p(t["excluded"], styles["body"]))
        for r in s["reasons"]:
            story.append(_p("- " + r, styles["small"]))

    # letter
    story.append(_p(t["letter"], styles["h2"]))
    letter = (documents or {}).get(lang)
    if letter is not None and letter.verified:
        story.extend(_letter_flowables(letter, styles))
    else:
        story.append(_p(t["noletter"], styles["body"]))

    story += [Spacer(1, 12), _p(disclaimer, styles["small"])]

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(2 * cm, 1.2 * cm, _clean(disclaimer))
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"{t['page']} {doc.page}")
        canvas.restoreState()

    buf = BytesIO()
    SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=2 * cm,
        title=f"{t['title']} - {c['name']}",
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
